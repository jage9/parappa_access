#!/usr/bin/env python3
"""Estimate DuckStation cue-submission to digital-loopback onset delays.

This reads one completed logs/duck-sessions directory and writes JSON to stdout.
It does not alter session files. The result is callback-relative loopback timing,
not physical speaker latency.
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/research/audio-python'))

import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate, fftconvolve, resample_poly

PREFIX_MS = 40
SEARCH_BEFORE_S = 0.15
SEARCH_AFTER_S = 0.45
CORRELATION_THRESHOLD = 0.8
COMPETING_EXCLUSION_MS = 5
BUTTONS = {'TRIANGLE', 'CIRCLE', 'X', 'SQUARE', 'L1', 'R1'}


def read_json(path, errors, label):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        errors.append(f'{label}: {type(exc).__name__}: {exc}')
        return {}


def read_events(path, errors):
    events = []
    try:
        with path.open(encoding='utf-8') as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except Exception as exc:
                    errors.append(f'events.jsonl line {line_number}: {type(exc).__name__}: {exc}')
    except Exception as exc:
        errors.append(f'events.jsonl: {type(exc).__name__}: {exc}')
    return events


def pcm_float(samples):
    samples = np.asarray(samples)
    if np.issubdtype(samples.dtype, np.integer):
        scale = float(-np.iinfo(samples.dtype).min)
        return samples.astype(np.float64) / scale
    return samples.astype(np.float64)


def channels(samples):
    samples = pcm_float(samples)
    if samples.ndim == 1:
        return samples, None
    if samples.ndim != 2 or samples.shape[1] < 1:
        raise ValueError('Expected mono or interleaved multichannel PCM')
    mid = samples.mean(axis=1)
    side = samples[:, 0] - samples[:, 1] if samples.shape[1] >= 2 else None
    return mid, side


def template_channel(samples, source_rate, target_rate, recording_side):
    samples = pcm_float(samples)
    if source_rate != target_rate:
        divisor = math.gcd(int(source_rate), int(target_rate))
        samples = resample_poly(samples, target_rate // divisor,
                                source_rate // divisor, axis=0)
    if samples.ndim == 1:
        mid = samples
        side = None
    elif samples.ndim == 2 and samples.shape[1] >= 2:
        mid = samples.mean(axis=1)
        side = samples[:, 0] - samples[:, 1]
    elif samples.ndim == 2 and samples.shape[1] == 1:
        mid = samples[:, 0]
        side = None
    else:
        raise ValueError('Expected mono or stereo cue PCM')

    prefix_length = min(len(mid), int(target_rate * PREFIX_MS / 1000))
    if prefix_length < 1:
        raise ValueError('Cue template is empty')
    mid = mid[:prefix_length]
    side = side[:prefix_length] if side is not None else None
    if side is not None and recording_side is not None and float(np.dot(side, side)) > 0:
        return side, 'side', prefix_length
    return mid, 'mid', prefix_length


def normalized_match(window, template, rate):
    template = np.asarray(template, dtype=np.float64)
    template = template - template.mean()
    template_energy = float(np.dot(template, template))
    if template_energy <= 1e-20:
        raise ValueError('Cue template has no AC energy')
    if len(window) < len(template):
        raise ValueError('Search window is shorter than cue template')

    score = np.abs(correlate(window, template, mode='valid', method='fft'))
    window_energy = fftconvolve(window * window, np.ones(len(template)), mode='valid')
    score = score / np.sqrt(np.maximum(window_energy, 1e-20) * template_energy)
    score = np.nan_to_num(score, nan=0.0, posinf=0.0, neginf=0.0)
    peak = int(np.argmax(score))

    competing = score.copy()
    exclusion = max(1, int(rate * COMPETING_EXCLUSION_MS / 1000))
    competing[max(0, peak - exclusion):min(len(competing), peak + exclusion + 1)] = 0
    runner_up = float(np.max(competing)) if len(competing) else 0.0
    return peak, float(score[peak]), max(0.0, float(score[peak]) - runner_up)


def delay_summary(rows):
    accepted = [row['delay_ms'] for row in rows if row.get('accepted') and
                row.get('delay_ms') is not None]
    return {
        'attempted': len(rows),
        'matched': len(accepted),
        'rejected': len(rows) - len(accepted),
        'minimum_ms': round(min(accepted), 3) if accepted else None,
        'median_ms': round(float(np.median(accepted)), 3) if accepted else None,
        'maximum_ms': round(max(accepted), 3) if accepted else None,
    }


def callback_clock(playback):
    callbacks = playback.get('callbacks', []) if isinstance(playback, dict) else []
    valid = [row for row in callbacks if isinstance(row, dict) and
             isinstance(row.get('perf_counter_ns'), (int, float)) and
             isinstance(row.get('sample_index'), (int, float))]
    if len(valid) < 2:
        raise ValueError('playback.json needs at least two timestamped callbacks')
    valid.sort(key=lambda row: row['perf_counter_ns'])
    hosts = np.asarray([row['perf_counter_ns'] for row in valid], dtype=np.float64)
    samples = np.asarray([row['sample_index'] for row in valid], dtype=np.float64)
    keep = np.concatenate(([True], np.diff(hosts) > 0))
    hosts, samples = hosts[keep], samples[keep]
    if len(hosts) < 2 or np.any(np.diff(samples) < 0):
        raise ValueError('playback.json callback clock is not monotonic')
    return callbacks, hosts, samples


def cue_events(events, errors):
    cues = []
    for line_number, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get('event') != 'cue_submission':
            continue
        button = event.get('button')
        before = event.get('before_ns')
        if button not in BUTTONS or not isinstance(before, (int, float)):
            errors.append(f'cue_submission {line_number}: missing/invalid button or before_ns')
            continue
        cues.append(dict(event, button=button, before_ns=int(before)))
    cues.sort(key=lambda row: row['before_ns'])
    return cues


def match_cues(session, cues, rate, mid, side, hosts, samples, errors):
    rows = []

    def to_sample(host_ns):
        return float(np.interp(host_ns, hosts, samples))

    def to_host(sample_index):
        return float(np.interp(sample_index, samples, hosts))

    for index, cue in enumerate(cues):
        button = cue['button']
        base = {
            'index': index + 1,
            'button': button,
            'before_ns': cue['before_ns'],
            'tick': cue.get('tick'),
            'accepted': False,
            'correlation': None,
            'margin': None,
            'delay_ms': None,
        }
        template_path = session / 'cue-wavs' / (button.lower() + '.wav')
        try:
            source_rate, source = wavfile.read(template_path)
            template, channel_name, prefix_length = template_channel(
                source, int(source_rate), rate, side)
            base['template_channel'] = channel_name
            base['template_prefix_ms'] = round(prefix_length * 1000 / rate, 3)
            base['template_source_rate'] = int(source_rate)

            host = cue['before_ns']
            if host < hosts[0] or host > hosts[-1]:
                raise ValueError('cue timestamp outside callback clock range')
            estimate = to_sample(host)
            lower = estimate - SEARCH_BEFORE_S * rate
            upper = estimate + SEARCH_AFTER_S * rate

            prior = next((row for row in reversed(cues[:index])
                          if row['button'] == button), None)
            following = next((row for row in cues[index + 1:]
                              if row['button'] == button), None)
            if prior:
                lower = max(lower, to_sample((prior['before_ns'] + host) / 2))
            if following:
                upper = min(upper, to_sample((host + following['before_ns']) / 2))

            max_start = len(side if channel_name == 'side' else mid) - len(template)
            first_start = max(0, int(math.ceil(lower)))
            last_start = min(max_start, int(math.floor(upper)))
            if last_start < first_start:
                raise ValueError('bounded cue search window is empty')
            recording = side if channel_name == 'side' else mid
            search = recording[first_start:last_start + len(template)]
            peak, correlation, margin = normalized_match(search, template, rate)
            peak_sample = first_start + peak
            peak_host = to_host(peak_sample)
            accepted = correlation >= CORRELATION_THRESHOLD
            base.update({
                'status': 'matched' if accepted else 'below_threshold',
                'accepted': accepted,
                'correlation': round(correlation, 6),
                'margin': round(margin, 6),
                'peak_sample': peak_sample,
                'peak_host_ns': int(round(peak_host)),
                'delay_ms': round((peak_host - host) / 1e6, 3) if accepted else None,
                'window_start_ms': round((to_host(first_start) - host) / 1e6, 3),
                'window_end_ms': round((to_host(last_start) - host) / 1e6, 3),
                'correlation_threshold': CORRELATION_THRESHOLD,
            })
        except Exception as exc:
            message = f"cue {index + 1} {button}: {type(exc).__name__}: {exc}"
            errors.append(message)
            base.update(status='not_analyzed', reason=f'{type(exc).__name__}: {exc}')
        rows.append(base)
    return rows


def capture_errors(manifest, playback):
    errors = []
    if isinstance(manifest, dict):
        for key in ('error', 'event_writer_error'):
            if manifest.get(key):
                errors.append(f'manifest.{key}: {manifest[key]}')
        for error in manifest.get('cleanup_errors', []) or []:
            errors.append(f'manifest.cleanup: {error}')
        dropped = (manifest.get('event_stats') or {}).get('dropped_events', 0)
        if dropped:
            errors.append(f'manifest dropped {dropped} events')
    if isinstance(playback, dict) and playback.get('error'):
        errors.append(f'playback.error: {playback["error"]}')
    return errors


def analyze(session):
    analysis_errors = []
    manifest = read_json(session / 'manifest.json', analysis_errors, 'manifest.json')
    playback = read_json(session / 'playback.json', analysis_errors, 'playback.json')
    events = read_events(session / 'events.jsonl', analysis_errors)
    cues = cue_events(events, analysis_errors)
    rows = []
    rate = None
    duration = None
    callback_count = 0
    callback_statuses = []
    callback_duration = None
    max_callback_gap = None
    device = playback.get('device') if isinstance(playback, dict) else None
    hosts = samples = None

    try:
        rate, waveform = wavfile.read(session / 'playback.wav')
        rate = int(rate)
        mid, side = channels(waveform)
        duration = len(mid) / rate if rate > 0 else None
        try:
            callbacks, hosts, samples = callback_clock(playback)
            callback_count = len(callbacks)
            statuses = {str(row.get('status')) for row in callbacks if row.get('status') is not None}
            callback_statuses = sorted(statuses)
            if len(hosts) > 1:
                callback_duration = (hosts[-1] - hosts[0]) / 1e9
                max_callback_gap = float(np.max(np.diff(hosts)) / 1e6)
        except Exception as exc:
            analysis_errors.append(f'callback clock: {type(exc).__name__}: {exc}')
        if hosts is not None and samples is not None:
            rows = match_cues(session, cues, rate, mid, side, hosts, samples, analysis_errors)
        else:
            rows = [dict(index=i + 1, button=cue['button'], before_ns=cue['before_ns'],
                         tick=cue.get('tick'), status='not_analyzed', accepted=False,
                         correlation=None, margin=None, delay_ms=None,
                         reason='callback clock unavailable') for i, cue in enumerate(cues)]
    except Exception as exc:
        analysis_errors.append(f'playback.wav: {type(exc).__name__}: {exc}')
        rows = [dict(index=i + 1, button=cue['button'], before_ns=cue['before_ns'],
                     tick=cue.get('tick'), status='not_analyzed', accepted=False,
                     correlation=None, margin=None, delay_ms=None,
                     reason='loopback audio unavailable') for i, cue in enumerate(cues)]

    half = len(rows) // 2
    report = {
        'session': session.name,
        'session_directory': str(session),
        'capture_status': manifest.get('status') if isinstance(manifest, dict) else None,
        'captured_duration_s': round(duration, 6) if duration is not None else None,
        'callback_duration_s': round(float(callback_duration), 6) if callback_duration is not None else None,
        'capture_errors': capture_errors(manifest, playback),
        'analysis_errors': analysis_errors,
        'callback_count': callback_count,
        'callback_statuses': callback_statuses,
        'maximum_callback_gap_ms': round(max_callback_gap, 3) if max_callback_gap is not None else None,
        'device': device,
        'cue_count': len(cues),
        'matched_cue_count': sum(bool(row.get('accepted')) for row in rows),
        'unique_matched_onsets': len({row['peak_sample'] for row in rows if row.get('accepted')}),
        'cue_delay_ms': delay_summary(rows),
        'early_half': delay_summary(rows[:half]),
        'late_half': delay_summary(rows[half:]),
        'cue_matches': rows,
        'method': {
            'template_prefix_ms': PREFIX_MS,
            'search_window_s': [-SEARCH_BEFORE_S, SEARCH_AFTER_S],
            'same_button_midpoint_boundaries': True,
            'accepted_when_correlation_at_least': CORRELATION_THRESHOLD,
            'competing_peak_exclusion_ms': COMPETING_EXCLUSION_MS,
            'channel': 'left-minus-right for cues with side-channel energy; mid fallback otherwise',
        },
        'limitations': 'Callback-relative digital loopback alignment; this does not measure physical speaker latency or listener-perceived timing.',
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path, help='Completed DuckStation session directory under logs/duck-sessions')
    args = parser.parse_args()
    session = args.session.resolve()
    if not session.is_dir():
        parser.error(f'session directory does not exist: {session}')
    print(json.dumps(analyze(session), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
