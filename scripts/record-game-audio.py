"""Bounded, opt-in playback recording for developer runs; never opens a microphone."""
import argparse
import queue
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools/research/audio-python'))
import pyaudiowpatch as audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=float, default=300)
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'logs') or not 0 < args.seconds <= 600:
        parser.error('Use a new logs/ output and a duration of at most 600 seconds.')
    pending = queue.Queue(maxsize=128)
    overflow = []

    def capture(data, frames, timing, status):
        try:
            pending.put_nowait(data)
        except queue.Full:
            overflow.append(True)
            return None, audio.paAbort
        return None, audio.paContinue

    with audio.PyAudio() as device:
        info = device.get_default_wasapi_loopback()
        if not info.get('isLoopbackDevice'):
            raise RuntimeError('Selected device is not playback loopback.')
        channels = int(info['maxInputChannels'])
        rate = int(info['defaultSampleRate'])
        with output.open('xb') as raw, wave.open(raw, 'wb') as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            with device.open(format=audio.paInt16, channels=channels, rate=rate,
                             input=True, input_device_index=info['index'],
                             frames_per_buffer=2048, stream_callback=capture):
                print(f'PLAYBACK_RECORDING rate={rate} channels={channels}', flush=True)
                deadline = time.monotonic() + args.seconds
                while time.monotonic() < deadline:
                    if args.stop_file and args.stop_file.exists():
                        break
                    if overflow:
                        raise RuntimeError('Playback capture queue overflowed.')
                    try:
                        wav.writeframesraw(pending.get(timeout=0.1))
                    except queue.Empty:
                        pass
        print(f'PLAYBACK_RECORDED {output}', flush=True)


if __name__ == '__main__':
    main()
