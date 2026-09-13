"""Summarize captured Stage 1 observations without inventing scoring windows."""
import argparse,json,statistics
from pathlib import Path

MASKS={'Triangle':0x10,'Circle':0x20,'Cross':0x40,'Square':0x80,'L1':4,'R1':8}
def stats(values):
    return dict(count=len(values),minimum=min(values),median=statistics.median(values),maximum=max(values)) if values else dict(count=0)

def analyze(session):
    events=[json.loads(line) for line in (session/'events.jsonl').read_text().splitlines()]
    keys=[e for e in events if e['event']=='keyboard' and e['edge']=='down']
    gameplay=True;key_context={}
    for event in sorted(events,key=lambda e:e['perf_counter_ns']):
        if event['event']=='retry_dialog_entered':gameplay=False
        elif event['event']=='clock_discontinuity':gameplay=True
        elif event['event'] in ('stage1_context','stage_context'):gameplay=event['valid']
        elif event['event']=='keyboard' and event['edge']=='down':key_context[event['perf_counter_ns']]=gameplay
    pads=[e for e in events if e['event']=='game_pad_change' and e['mask']]
    responses=[e for e in events if e['event']=='cursor_consumed' and e.get('cursor','').startswith('response') and 'button' in e]
    used=set();presses=[]
    for key in keys:
        candidates=[(i,p) for i,p in enumerate(pads) if i not in used and
                    p['mask']&MASKS[key['button']] and 0<=(p['perf_counter_ns']-key['perf_counter_ns'])<=250_000_000]
        row=dict(button=key['button'],os_hook_ns=key['perf_counter_ns'],injected=key.get('injected',False),
                 gameplay=key_context[key['perf_counter_ns']])
        if not row['gameplay']:presses.append(row);continue
        if candidates:
            i,p=candidates[0];used.add(i)
            row.update(game_observed_ns=p['perf_counter_ns'],os_to_observed_game_ms=(p['perf_counter_ns']-key['perf_counter_ns'])/1e6,
                       observation_gap_ms=p['observation_gap_ns']/1e6,tick=p['tick'],score=p['score'])
            nearest=sorted(responses,key=lambda r:abs(r['perf_counter_ns']-p['perf_counter_ns']))
            if nearest and abs(nearest[0]['perf_counter_ns']-p['perf_counter_ns'])<500_000_000:
                r=nearest[0];row.update(nearest_response_button=r['button'],
                    response_marker_delta_ms=(p['perf_counter_ns']-r['perf_counter_ns'])/1e6)
        presses.append(row)
    manifest=json.loads((session/'manifest.json').read_text())
    return dict(session=str(session),key_downs=len(keys),observed_nonzero_pad_changes=len(pads),
        gameplay_key_downs=sum(p['gameplay'] for p in presses),menu_key_downs=sum(not p['gameplay'] for p in presses),
        matched_presses=len(used),unmatched_pad_changes=len(pads)-len(used),
        os_to_observed_game_ms=stats([p['os_to_observed_game_ms'] for p in presses if 'os_to_observed_game_ms' in p]),
        presses=presses,monitor_summaries=[e for e in events if e['event']=='monitor_summary'],
        cue_submissions=sum(e['event']=='cue_submission' for e in events),
        cue_suppressed=[e for e in events if e['event']=='cue_suppressed'],
        errors=[e for e in events if e['event'].endswith('_error')],capture_manifest=manifest,
        limitations=['OS hook receipt is not physical key closure or the emulator callback.',
          'Game input is a polled RAM observation; observation gaps bound its sampling uncertainty.',
          'Response cursor markers are not calibrated judgment centers. Deltas do not prove early/late judgments.',
          'Audio waveform analysis is separate; submission timestamps do not measure audible latency.'])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('session',type=Path);args=parser.parse_args()
    print(json.dumps(analyze(args.session.resolve()),indent=2))
