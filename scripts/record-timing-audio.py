"""Bounded WASAPI playback-loopback capture with raw timing metadata; no microphone."""
import argparse
import json
import queue
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_AUDIO_SECONDS = 900
sys.path.insert(0, str(ROOT / 'tools/research/audio-python'))
import pyaudiowpatch as audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seconds', type=float, default=40)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--loopback-name', help='Exact playback-loopback device name; otherwise use default.')
    args = parser.parse_args()
    output = args.output.resolve()
    metadata = output.with_suffix('.json')
    if (not output.is_relative_to(ROOT / 'logs') or output.suffix.lower() != '.wav'
            or not 0 < args.seconds <= MAX_AUDIO_SECONDS):
        parser.error(f'Use a new logs/*.wav output and at most {MAX_AUDIO_SECONDS} seconds.')
    if output.exists() or metadata.exists():
        parser.error('Output or metadata already exists; choose a new name.')
    pending = queue.Queue(maxsize=256)
    failed = []
    sample_index = 0
    report = {'callbacks': [], 'clock_pairs': [], 'error': None,
              'python_executable': sys.executable, 'python_version': sys.version,
              'audio_module_file': getattr(audio, '__file__', None),
              'audio_module_origin': getattr(getattr(audio, '__spec__', None), 'origin', None),
              'clock': 'perf_counter_ns; raw PortAudio seconds, not calibrated audible time',
              'measurement_point': 'WASAPI playback loopback, not physical speakers'}

    def capture(data, frames, timing, status):
        nonlocal sample_index
        host_ns = time.perf_counter_ns()
        item = {'sample_index': sample_index, 'frames': frames,
                'perf_counter_ns': host_ns, 'time_info': dict(timing), 'status': status}
        sample_index += frames
        try:
            pending.put_nowait((data, item))
        except queue.Full:
            if not failed:
                failed.append('Capture queue overflow; recording is incomplete.')
            return None, audio.paAbort
        return None, audio.paContinue

    def clock_pair(stream, label):
        before = time.perf_counter_ns()
        pa_time = stream.get_time()
        after = time.perf_counter_ns()
        report['clock_pairs'].append({'label': label, 'perf_before_ns': before,
                                     'portaudio_time': pa_time, 'perf_after_ns': after})

    # Exclusive opens preserve earlier recordings, including on failure.
    with metadata.open('x', encoding='utf-8') as meta:
        try:
            if not callable(getattr(audio, 'PyAudio', None)):
                raise RuntimeError('Loaded audio module has no PyAudio class; see module origin in metadata.')
            with audio.PyAudio() as device:
                if args.loopback_name:
                    matches = [d for d in device.get_loopback_device_info_generator()
                               if d['name'] == args.loopback_name]
                    if len(matches) != 1:
                        raise RuntimeError('Expected exactly one matching playback-loopback device.')
                    info = matches[0]
                else:
                    info = device.get_default_wasapi_loopback()
                if not info.get('isLoopbackDevice'):
                    raise RuntimeError('Selected device is not playback loopback.')
                host = device.get_host_api_info_by_index(info['hostApi'])
                if host['type'] != audio.paWASAPI:
                    raise RuntimeError('Loopback host API is not WASAPI.')
                rate, channels = int(info['defaultSampleRate']), int(info['maxInputChannels'])
                report.update(device=info, host_api=host, rate=rate, channels=channels,
                              sample_width=2, requested_frames_per_buffer=480)
                with output.open('xb') as raw, wave.open(raw, 'wb') as wav:
                    wav.setnchannels(channels)
                    wav.setsampwidth(2)
                    wav.setframerate(rate)
                    stream = device.open(format=audio.paInt16, channels=channels, rate=rate,
                                         input=True, input_device_index=info['index'],
                                         frames_per_buffer=480, stream_callback=capture, start=False)
                    try:
                        clock_pair(stream, 'before_start')
                        deadline = time.monotonic() + args.seconds
                        stream.start_stream()
                        clock_pair(stream, 'after_start')
                        report['reported_input_latency_s'] = stream.get_input_latency()
                        print(f'TIMING_RECORDING rate={rate} channels={channels}', flush=True)
                        while time.monotonic() < deadline:
                            if failed:
                                raise RuntimeError(failed[0])
                            if args.stop_file and args.stop_file.exists():
                                break
                            if not stream.is_active():
                                raise RuntimeError('Capture stream stopped unexpectedly.')
                            try:
                                data, item = pending.get(timeout=0.05)
                            except queue.Empty:
                                continue
                            wav.writeframesraw(data)
                            report['callbacks'].append(item)
                        clock_pair(stream, 'before_stop')
                    finally:
                        try:
                            stream.stop_stream()
                        except Exception as exc:
                            report.setdefault('cleanup_errors', []).append(str(exc))
                        try:
                            stream.close()
                        except Exception as exc:
                            report.setdefault('cleanup_errors', []).append(str(exc))
                        while not pending.empty():
                            data, item = pending.get_nowait()
                            wav.writeframesraw(data)
                            report['callbacks'].append(item)
                        report['written_frames'] = wav.getnframes()
                    if failed:
                        raise RuntimeError(failed[0])
                    if report.get('cleanup_errors'):
                        raise RuntimeError('Stream cleanup failed; see metadata.')
        except BaseException as exc:
            report['error'] = str(exc)
            raise
        finally:
            json.dump(report, meta, indent=2)
    print(f'TIMING_RECORDED {output}', flush=True)


if __name__ == '__main__':
    main()
