"""Opt-in spoken menu launcher with bounded playback-loopback capture."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
MENU_PATH = ROOT / 'scripts' / 'accessible-menu.py'

MENU_SPEC = importlib.util.spec_from_file_location('accessible_menu', MENU_PATH)
if MENU_SPEC is None or MENU_SPEC.loader is None:
    raise RuntimeError(f'Could not load accessible menu from {MENU_PATH}.')
accessible_menu = importlib.util.module_from_spec(MENU_SPEC)
MENU_SPEC.loader.exec_module(accessible_menu)


class TimingMenu(accessible_menu.Menu):
    """Menu subclass that records playback while a human plays checkpoints."""

    def __init__(self, speech, loopback_name, popen_factory=None):
        super().__init__(speech)
        self.loopback_name = loopback_name
        self._popen = popen_factory or subprocess.Popen
        self._recorded_sessions = set()
        self._recorder = None
        self._recorder_session = None
        self._recorder_stop_file = None
        self._recorder_log = None
        self._capture_checkpoint = None

    def play(self, native=False, checkpoint=None):
        self._capture_checkpoint = checkpoint
        super().play(native=native, checkpoint=checkpoint)

    def before_play_resume(self):
        if self._capture_checkpoint is not None:
            if not self.start_recorder(Path(self.demo_log).parent):
                raise RuntimeError('Recording could not start. The game is still paused. '
                                   'Choose a checkpoint again or 0 to close; see playback-recorder.log in the session folder.')
            self.speech.say('Recording ready.')

    def start_recorder(self, session):
        session = Path(session).resolve()
        if session in self._recorded_sessions:
            return self._recorder is not None and self._recorder.poll() is None
        self._recorded_sessions.add(session)

        output = session / 'playback.wav'
        log_path = session / 'playback-recorder.log'
        stop_file = session / f'playback-{uuid.uuid4().hex}.stop'
        # All recorder dependencies are local; exclude user/site startup hooks.
        command = [sys.executable, '-I', '-S', str(ROOT / 'scripts' / 'record-timing-audio.py'),
                   '--output', str(output), '--seconds', '180', '--stop-file', str(stop_file),
                   '--loopback-name', self.loopback_name]
        try:
            with log_path.open('x', encoding='utf-8') as output_log:
                recorder = self._popen(
                    command, cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=output_log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f'Playback capture could not start. '
                  f'Recorder log: {log_path}. {exc}', flush=True)
            return

        self._recorder = recorder
        self._recorder_session = session
        self._recorder_stop_file = stop_file
        self._recorder_log = log_path
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if recorder.poll() is not None:
                self._capture_warning('Playback capture failed to initialize.')
                self.stop_recorder()
                return
            try:
                if 'TIMING_RECORDING' in log_path.read_text(errors='replace'):
                    break
            except OSError:
                pass
            time.sleep(0.05)
        else:
            self._capture_warning('Playback capture did not become ready.')
            self.stop_recorder()
            return
        print(f'Playback loopback capture started (up to 180 seconds, no microphone). '
              f'Recorder log: {log_path}.', flush=True)
        return True

    def _stop_recorder_process(self, recorder):
        try:
            return recorder.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._capture_warning('Capture did not stop on request; terminating the recorder process.')
            try:
                recorder.terminate()
            except OSError:
                pass
            try:
                return recorder.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    recorder.kill()
                except OSError as exc:
                    self._capture_warning(f'Could not kill the stuck recorder: {exc}')
                try:
                    return recorder.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    self._capture_warning(f'Could not reap the recorder process: {exc}')
        except OSError as exc:
            self._capture_warning(f'Could not wait for the recorder process: {exc}')
        return None

    def _capture_warning(self, message):
        log_path = self._recorder_log
        suffix = f' See {log_path}.' if log_path else ''
        state = 'Game remains paused.' if self.paused else 'Gameplay continues.'
        print(f'{message} {state}{suffix}', flush=True)

    def stop_recorder(self):
        recorder = self._recorder
        if recorder is None:
            return
        log_path = self._recorder_log
        return_code = None
        try:
            if recorder.poll() is None:
                try:
                    with self._recorder_stop_file.open('xb'):
                        pass
                except FileExistsError:
                    pass
                except OSError as exc:
                    self._capture_warning(f'Could not signal the recorder stop file: {exc}')
                    try:
                        recorder.terminate()
                    except OSError:
                        pass
                return_code = self._stop_recorder_process(recorder)
            else:
                return_code = recorder.returncode
        except OSError as exc:
            self._capture_warning(f'Could not clean up the recorder: {exc}')
        finally:
            self._recorder = None
            self._recorder_session = None
            self._recorder_stop_file = None
            self._recorder_log = None
        if return_code not in (None, 0):
            state = 'Game remains paused.' if self.paused else 'Gameplay continued.'
            print(f'Playback capture failed with exit code {return_code}. {state} '
                  f'Recorder log: {log_path}.', flush=True)

    def stop_demo(self):
        self.stop_recorder()
        super().stop_demo()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loopback-name', required=True,
                        help='Exact WASAPI playback-loopback device name.')
    parser.add_argument('--no-speech', action='store_true')
    parser.add_argument('--speech-test', action='store_true')
    args = parser.parse_args(argv)

    speech = accessible_menu.Speech(not args.no_speech)
    print('Timing diagnostic: checkpoint play captures playback loopback for up to '
          '180 seconds (no microphone). Capture stops when you close the demo or '
          'change stage. The game starts only after recording is ready; the '
          '180-second recording limit does not stop gameplay.', flush=True)
    if args.speech_test:
        speech.say('Prism speech test. PaRappa menu speech is ready.')
        input('Press Enter to finish the speech test.')
        speech.stop()
        return
    try:
        TimingMenu(speech, args.loopback_name).run()
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == '__main__':
    main()
