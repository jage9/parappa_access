"""Prism-spoken launcher for the local PaRappa accessibility project."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import msvcrt
import subprocess
import sys
import threading
import time
import launcher_settings
from duckstation_checkpoint_catalog import list_checkpoints

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / 'logs'
COMMAND = LOGS / 'demo-command.txt'
DEMO_LOG = LOGS / 'play-stage1.log'
CONFIG = ROOT / 'tools' / 'pcsx-redux' / 'pcsx.json'
# Temporary diagnostic graphics reduction; never changes emulation speed.
LOW_GRAPHICS = {'Dither': 0, 'LinearFiltering': False}
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tools' / 'prism-python'))


class Speech:
    def __init__(self, enabled=True):
        self.context = self.backend = None
        self.lock = threading.RLock()
        if enabled:
            try:
                import prism
                self.context = prism.Context()
                self.backend = self.context.create_best()
                print('Speech backend:', self.backend.name)
            except Exception as exc:
                print('Prism unavailable; using console text:', exc)

    def say(self, text):
        with self.lock:
            if self.backend:
                try:
                    self.backend.speak(text, interrupt=True)
                    return 'backend_returned'  # Avoid duplicate console speech.
                except Exception as exc:
                    print('Speech failed; console text remains available:', exc)
                    self.backend = None
            print(text, flush=True)
            return 'console_fallback'

    def stop(self):
        with self.lock:
            if self.backend:
                try:
                    self.backend.stop()
                except Exception:
                    pass


class WindowMessages:
    """Native message dialogs for launcher errors, rather than console output."""
    backend = None

    def say(self, text):
        import window_menu
        window_menu.message_box(text)

    def stop(self):
        pass


class Menu:
    def __init__(self, speech, preferences_path=None, legacy_panning_path=None, game_speech_enabled=None, windowed=False):
        self.speech = speech
        self.game_speech_enabled = (speech.backend is not None if game_speech_enabled is None else game_speech_enabled)
        self.windowed = windowed
        if windowed:
            self.speech = WindowMessages()
        self.demo = None
        self.watcher = None
        self.centered_audio = True
        self.preferences_path = Path(preferences_path or launcher_settings.SETTINGS_PATH)
        self.legacy_panning_path = Path(legacy_panning_path or launcher_settings.LEGACY_PANNING_PATH)
        preferences = launcher_settings.load_settings(self.preferences_path, self.legacy_panning_path)
        self.panned_cues = preferences['panned_cues']
        self.audio_output = preferences['audio_output']
        self.handoff_sound = preferences['handoff_sound']
        self.cue_volume = preferences['cue_volume']
        self.paused = True
        self.demo_log = DEMO_LOG
        self._setup_checked = False
        self._practice_audio = []
        LOGS.mkdir(exist_ok=True)

    def save_settings(self):
        launcher_settings.save_settings({
            'panned_cues': self.panned_cues,
            'audio_output': self.audio_output,
            'handoff_sound': self.handoff_sound,
            'cue_volume': self.cue_volume,
        }, self.preferences_path)

    @staticmethod
    def read_key():
        """Read one console key, consuming the second byte of extended keys."""
        window = sys.modules.get('window_menu')
        if window is not None and window.is_active():
            key = window.read_key()
            if key == '__close__':
                raise EOFError
            return key
        key = msvcrt.getwch()
        if key in ('\x00', '\xe0'):
            return {'H': 'up', 'P': 'down', 'K': 'left', 'M': 'right'}.get(msvcrt.getwch(), '')
        if key == '\x03':
            raise KeyboardInterrupt
        return key.lower()

    def menu_surface(self):
        if self.windowed:
            import window_menu
            return window_menu
        from console_menu_cursor import ConsoleMenuCursor
        return ConsoleMenuCursor()

    def launch(self, lua, log, interactive=False):
        args = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                '-File', str(ROOT / 'scripts' / 'run-redux.ps1'), '-Debugger',
                '-Lua', lua, '-Log', str(log), '-Wait']
        if interactive:
            args.append('-Interactive')
        # The helper stays hidden; the requested interactive emulator is visible.
        with (LOGS / 'menu-launcher.log').open('w', encoding='utf-8') as output:
            return subprocess.Popen(args, cwd=ROOT, stdout=output,
                                    stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW)

    def running(self):
        return self.demo is not None and self.demo.poll() is None

    def command(self, value):
        if not self.running():
            raise RuntimeError('No demo is running. Choose 1 to select a checkpoint.')
        old_size = self.demo_log.stat().st_size if self.demo_log.exists() else 0
        temp = COMMAND.with_suffix('.tmp')
        temp.write_text(value, encoding='ascii')
        temp.replace(COMMAND)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if value == 'quit' and not self.running():
                return
            if self.demo_log.exists():
                with self.demo_log.open('rb') as f:
                    f.seek(old_size)
                    if ('DEMO_COMMAND ' + value).encode() in f.read():
                        return
            if not self.running():
                raise RuntimeError(f'Demo ended. See {self.demo_log}.')
            time.sleep(0.05)
        raise RuntimeError(f'Demo did not acknowledge the command. See {self.demo_log}.')

    def stop_demo(self):
        if self.running():
            self.command('quit')
            self.demo.wait(timeout=8)
        if self.watcher:
            self.watcher.join(timeout=8)
            if self.watcher.is_alive():
                raise RuntimeError('Waiting for audio preference restoration; try again shortly.')
            self.watcher = None
        self.demo = None
        self.paused = True

    def watch_demo(self, process, previous_mono, restore_mono, previous_gui=None, previous_graphics=None):
        """Announce known results, then restore our temporary mixer preference."""
        game_speech = Speech(self.game_speech_enabled)
        last_sequence = 0
        last_native_sequence = 0
        speech_log = self.demo_log.parent / 'speech-events.jsonl'

        def say_event(text, source, sequence):
            # This runs in the host watcher, never the emulation callback.
            # A successful backend return is not proof the user heard speech.
            def record(status):
                try:
                    with speech_log.open('a', encoding='utf-8') as f:
                        f.write(json.dumps({'host_ns': time.perf_counter_ns(),
                                            'source': source, 'sequence': sequence,
                                            'text': text, 'status': status}) + '\n')
                except OSError:
                    pass  # Diagnostic failures must not prevent speech.
            record('requested')
            record(game_speech.say(text) or 'returned')

        while process.poll() is None:
            try:
                event = json.loads((LOGS / 'native-event.json').read_text(encoding='utf-8'))
                if event['sequence'] > last_native_sequence:
                    last_native_sequence = event['sequence']
                    text = event['text']
                    if event.get('hint'):
                        text = (text + ' ' if text else '') + event['hint']
                    say_event(text, 'native', event['sequence'])
            except (OSError, ValueError, KeyError, TypeError):
                pass
            try:
                event = json.loads((LOGS / 'demo-result.json').read_text(encoding='ascii'))
                if event['sequence'] > last_sequence and event['kind'] == 'failure':
                    last_sequence = event['sequence']
                    say_event(f"Stage {event.get('stage', 1)} not cleared. Score {event['score']}.", 'failure', event['sequence'])
                elif event['sequence'] > last_sequence and event['kind'] == 'clear':
                    last_sequence = event['sequence']
                    say_event(f"Stage {event.get('stage', 1)} cleared. Score {event['score']}.", 'clear', event['sequence'])
                elif event['sequence'] > last_sequence and event['kind'] == 'score_live':
                    last_sequence = event['sequence']
                    say_event(f"Score {event['score']}.", 'score_live', event['sequence'])
                elif event['sequence'] > last_sequence and event['kind'] == 'score':
                    last_sequence = event['sequence']
                    say_event(f"Score {event['score']}. Game paused. Enter 2 to resume.", 'score', event['sequence'])
            except (OSError, ValueError, KeyError, TypeError):
                pass  # A writer may be midway through replacing its result.
            time.sleep(0.1)
        game_speech.stop()
        self.restore_preferences(previous_mono, restore_mono, previous_gui, previous_graphics)

    def restore_preferences(self, previous_mono, restore_mono, previous_gui=None, previous_graphics=None):
        if not restore_mono and not previous_gui and not previous_graphics:
            return
        try:
            config = json.loads(CONFIG.read_text(encoding='utf-8'))
            # A GUI close may save before Lua's Quitting callbacks run. Preserve
            # all other current settings; never replace the file with a backup.
            changed = False
            if restore_mono and config['SPU']['Mono'] is True and previous_mono is False:
                config['SPU']['Mono'] = previous_mono
                changed = True
            for key, original in (previous_gui or {}).items():
                applied = key == 'FullWindowRender'
                if config['gui'].get(key) == applied and original != applied:
                    config['gui'][key] = original
                    changed = True
            for key, original in (previous_graphics or {}).items():
                if config['emulator'].get(key) == LOW_GRAPHICS[key] and original != LOW_GRAPHICS[key]:
                    config['emulator'][key] = original
                    changed = True
            if changed:
                temp = CONFIG.with_name('pcsx.menu-audio.tmp')
                temp.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
                temp.replace(CONFIG)
        except (OSError, ValueError, KeyError) as exc:
            print('Could not restore the original playback preferences:', exc, flush=True)

    def choose_checkpoint(self):
        """Return a selected verified checkpoint stage, or None when canceled."""
        was_playing = self.running() and not self.paused
        if was_playing:
            self.command('pause')
            self.paused = True
        self.speech.say('Choose a stage checkpoint. Enter a stage from 1 to 6, or 0 to cancel.')
        while True:
            choice = input('Checkpoint stage (1-6, 0 cancel): ').strip()
            if choice == '0':
                self.speech.say('Cancelled.')
                if was_playing and self.running():
                    self.command('resume')
                    self.paused = False
                return None
            if choice in {'1', '2', '3', '4', '5', '6'}:
                self.speech.say(f'Stage {choice}.')
                return int(choice)
            self.speech.say('Choose a stage from 1 to 6, or 0 to cancel.')

    def play(self, native=False, checkpoint=None):
        self._close_practice_audio()
        if checkpoint is not None:
            if type(checkpoint) is not int or not 1 <= checkpoint <= 6:
                raise RuntimeError('Checkpoint stage must be an integer from 1 to 6.')
            native = True
        self.stop_demo()
        if not native and not (LOGS / 'stage1-gameplay.sstate').exists():
            self.speech.say('Preparing Stage 1. Menu buttons will be pressed automatically.')
            prep = self.launch('scripts/prepare-stage1.lua', LOGS / 'prepare-stage1.log')
            if prep.wait() != 0 or not (LOGS / 'stage1-gameplay.sstate').exists():
                raise RuntimeError('Preparation failed. See logs/prepare-stage1.log.')
        COMMAND.unlink(missing_ok=True)
        (LOGS / 'demo-result.json').unlink(missing_ok=True)
        (LOGS / 'native-event.json').unlink(missing_ok=True)
        if checkpoint is not None:
            (LOGS / 'checkpoint-stage.txt').write_text(str(checkpoint), encoding='ascii')
        (LOGS / 'demo-audio.txt').write_text('centered' if self.centered_audio else 'original', encoding='ascii')
        (LOGS / 'demo-panning.txt').write_text('on' if self.panned_cues else 'off', encoding='ascii')
        previous_config = json.loads(CONFIG.read_text(encoding='utf-8'))
        previous_mono = previous_config['SPU']['Mono']
        previous_graphics = {key: previous_config['emulator'][key] for key in LOW_GRAPHICS}
        previous_gui = {key: previous_config['gui'][key]
                        for key in ('ShowMenu', 'ShowAssembly', 'FullWindowRender')}
        # Keep each attempt, including console retries, for later investigation.
        session = LOGS / 'play-sessions' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        session.mkdir(parents=True)
        self.demo_log = session / 'redux.log'
        self.demo_log.write_text('', encoding='utf-8')
        paths = [ROOT / 'tools/pcsx-redux/pcsx-redux.main',
                 ROOT / 'tools/pcsx-redux/pcsx-redux.exe',
                 ROOT / 'tools/pcsx-redux/openbios.bin',
                 ROOT / 'docs/disc-metadata.md', *sorted((ROOT / 'scripts').glob('*.lua')),
                 *sorted((ROOT / 'sounds').glob('*.wav')),
                 ROOT / 'scripts/accessible-menu.py']
        manifest = {'centered_audio': self.centered_audio,
                    'runtime_preferences': {'gui': {'ShowMenu': False, 'ShowAssembly': False,
                                                      'FullWindowRender': True},
                                            'spu_before': previous_config['SPU'],
                                            'gui_before': previous_gui,
                                            'graphics': LOW_GRAPHICS,
                                            'graphics_before': previous_graphics},
                    'startup': ('checkpoint' if checkpoint is not None else
                                ('native' if native else 'stage1_state')),
                    'panned_cues': self.panned_cues,
                    'identity_reference': 'docs/disc-metadata.md',
                    'sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in paths if p.is_file()}}
        if checkpoint is not None:
            manifest['stage'] = checkpoint
            manifest['mode'] = 'checkpoint'
        (session / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        (LOGS / 'latest-play-session.txt').write_text(str(session.relative_to(ROOT)), encoding='utf-8')
        print(f'Play session log: {self.demo_log}', flush=True)
        previous_config['emulator'].update(LOW_GRAPHICS)
        config_temp = CONFIG.with_name('pcsx.menu-graphics.tmp')
        config_temp.write_text(json.dumps(previous_config, indent=2) + '\n', encoding='utf-8')
        config_temp.replace(CONFIG)
        try:
            lua = ('scripts/checkpoint-play.lua' if checkpoint is not None else
                   'scripts/native-play.lua' if native else 'scripts/stage1-play.lua')
            self.demo = self.launch(lua, self.demo_log, interactive=True)
        except Exception:
            self.restore_preferences(previous_mono, False, previous_graphics=previous_graphics)
            raise
        self.watcher = threading.Thread(target=self.watch_demo,
                                       args=(self.demo, previous_mono, self.centered_audio and not previous_mono, previous_gui, previous_graphics),
                                       daemon=True)
        self.watcher.start()
        if native and checkpoint is None:
            deadline = time.monotonic() + 20
            while 'NATIVE_READY' not in self.demo_log.read_text(errors='replace'):
                if not self.running() or time.monotonic() >= deadline:
                    raise RuntimeError(f'Original-game launch failed. See {self.demo_log}.')
                time.sleep(0.1)
            self.paused = False
            self.speech.say('Original game starting. Switch to PCSX Redux with Alt Tab. '
                            'Left and Right change the title selection; X confirms. Enter is the game Start button. '
                            'Opening scenes play normally. E reads your score during play. H reads menu controls. '
                            'Return here and enter 0 to quit.')
            return
        ready_marker = (f'CHECKPOINT_READY stage={checkpoint} paused=true'
                        if checkpoint is not None else 'CURSOR_READY paused=true')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if ready_marker in self.demo_log.read_text(errors='replace'):
                break
            if not self.running():
                details = [line for line in self.demo_log.read_text(errors='replace').splitlines()
                           if 'FAILED' in line]
                label = 'Checkpoint launch failed' if checkpoint is not None else 'Launch failed'
                raise RuntimeError(f'{label}. See {self.demo_log}. ' +
                                   (details[-1] if details else 'See logs/menu-launcher.log.'))
            time.sleep(0.1)
        else:
            raise RuntimeError(f'Demo did not become ready. See {self.demo_log}.')
        self.paused = True
        stage_name = f'Stage {checkpoint}' if checkpoint is not None else 'Stage 1'
        self.speech.say(f'{stage_name} ready and paused. Return to this console with Alt Tab if needed. '
                        'Press Enter here to start, then Alt Tab to '
                        'PCSX Redux for keyboard input. Alt Tab back here and enter 2 to pause. '
                        'Enter 1 to choose another checkpoint, or 0 to quit. '
                        'There is no play time limit. Enter 0 here when you want to finish.')
        input()
        self.speech.stop()
        self.before_play_resume()
        self.command('resume')
        self.paused = False
        print('Playing. Commands: 1 choose a checkpoint; 2 pause; 0 quit.', flush=True)

    def before_play_resume(self):
        """Optional diagnostics prepare while the new checkpoint is paused."""

    def _close_practice_audio(self):
        for sounds in self._practice_audio:
            sounds.close()
        self._practice_audio.clear()

    def audition(self):
        self.close_cue_preview()
        self.stop_demo()
        from launcher_practice import PracticeSounds

        def report(error):
            def show_error():
                if not sounds.closed:
                    self.speech.say('Practice audio unavailable: ' + str(error))
            if self.windowed:
                import window_menu
                window_menu.call_soon(show_error)
            else:
                self.speech.say('Practice audio unavailable: ' + str(error))

        sounds = PracticeSounds(ROOT, self.audio_output, self.panned_cues,
                                self.cue_volume, on_error=report)
        self._practice_audio.append(sounds)
        try:
            self.practice_keys(sounds)
        finally:
            sounds.close(wait=False)

    @staticmethod
    def print_list_menu(title, items, selected, instructions):
        """Print a compact one-item-per-line menu for console screen readers."""
        print(title, flush=True)
        for index, (key, label) in enumerate(items):
            marker = '>' if index == selected else ' '
            print(f'{marker} {key}. {label}', flush=True)
        print(instructions, flush=True)

    @staticmethod
    def menu_item_label(items, selected):
        return items[selected][1]

    def _preview_error_ready(self):
        if self.windowed:
            import window_menu
            window_menu.call_soon(self._report_preview_error)

    def _report_preview_error(self):
        from launcher_preview import take_preview_error
        error = take_preview_error(self)
        if error:
            self.speech.say('Preview unavailable: ' + error)

    def prepare_cue_preview(self):
        from launcher_preview import prepare_preview
        prepare_preview(self, on_error=self._preview_error_ready)

    def preview_cue_volume(self):
        from launcher_preview import preview_volume
        if not self.windowed:
            self._report_preview_error()
        preview_volume(self, on_error=self._preview_error_ready)

    def close_cue_preview(self):
        from launcher_preview import close_preview
        close_preview(self)

    def select_audio_output(self):
        """Choose a shared DuckStation/cue/loopback endpoint by its exact name."""
        import audio_devices

        choices = self.audio_choices(refresh=True)
        items = [(str(index), name or 'System default') for index, name in enumerate(choices, 1)]
        items.append(('0', 'Cancel'))
        selected = choices.index(self.audio_output) if self.audio_output in choices else 0
        cursor = self.menu_surface()
        instructions = 'Arrows to move, Enter selects. Or type a number and press Enter. Escape cancels.'
        cursor.show('Audio device', items, selected, instructions)
        self.announce_control('Audio device. ' + instructions + ' ' + self.spoken_menu_item(items, selected))
        try:
            digits = ''
            while True:
                key = self.read_key()
                if key == '\x1b':
                    self.announce_entry('Cancelled.')
                    return False
                if key.startswith('select:'):
                    selected = int(key.split(':', 1)[1])
                    cursor.move(selected)
                    self.announce_control(self.spoken_menu_item(items, selected))
                    continue
                if key in ('up', 'down'):
                    selected = (selected + (-1 if key == 'up' else 1)) % len(items)
                    digits = ''
                    cursor.move(selected)
                    self.announce_control(self.spoken_menu_item(items, selected))
                    continue
                if key.isdecimal():
                    digits += key
                    self.announce_entry(digits)
                    continue
                if key == '\x08':
                    digits = digits[:-1]
                    continue
                if key not in ('\r', '\n'):
                    continue

                # msvcrt reads one character at a time. Collect digits until Enter
                # so device lists with ten or more entries remain addressable.
                choice = int(digits) if digits else int(items[selected][0])
                digits = ''

                if choice == 0:
                    self.announce_entry('Cancelled.')
                    return False
                if 1 <= choice <= len(choices):
                    old_audio_output = self.audio_output
                    self.close_cue_preview()
                    self.audio_output = choices[choice - 1]
                    self.save_settings()
                    if self.audio_output != old_audio_output:
                        self.preview_cue_volume()
                    self.announce_control('Audio device ' + (self.audio_output or 'System default') + '.')
                    return True
                self.announce_entry('Enter a listed number, or 0 to cancel.')
        finally:
            cursor.finish()

    def audio_choices(self, refresh=False):
        if refresh or getattr(self, '_audio_choices', None) is None:
            import audio_devices
            self._audio_choices = [None] + [device.name for device in audio_devices.list_outputs()]
        return self._audio_choices

    @staticmethod
    def spoken_menu_item(items, selected, numbered=True):
        key, label = items[selected]
        return f'{key}. {label}.' if numbered else f'{label}.'

    def announce_control(self, text):
        """Native controls provide their own reviewable focus/selection speech."""
        if not self.windowed:
            self.announce_entry(text)

    def announce_entry(self, text):
        if not hasattr(self, '_entry_speech'):
            from launcher_entry_speech import EntrySpeech
            self._entry_speech = EntrySpeech(enabled=self.game_speech_enabled)
        self._entry_speech.say(text)

    def stop_entry_speech(self):
        if hasattr(self, '_entry_speech'):
            self._entry_speech.stop()

    def settings_menu(self):
        cursor = self.menu_surface()
        selected = 0
        instructions = ('Arrows to move, Enter or number keys select. '
                        'Left and right change settings.')

        def show():
            cursor.show('Settings', self._settings_items(), selected, instructions)
            if self.windowed:
                self.prepare_cue_preview()
            self.announce_control('Settings. ' + instructions + ' ' +
                                self.spoken_menu_item(self._settings_items(), selected, numbered=True))

        show()
        try:
            while True:
                key = self.read_key()
                options = self._settings_items()
                if key in ('0', '\x1b'):
                    return
                if key.startswith('select:'):
                    selected = int(key.split(':', 1)[1])
                    cursor.move(selected)
                    self.announce_control(self.spoken_menu_item(options, selected))
                    continue
                if key in ('up', 'down'):
                    selected = (selected + (-1 if key == 'up' else 1)) % len(options)
                    cursor.move(selected)
                    self.announce_control(self.spoken_menu_item(options, selected))
                    continue
                if key in ('left', 'right'):
                    old_volume = self.cue_volume
                    old_audio_output = self.audio_output
                    self._adjust_setting(options[selected][0], -10 if key == 'left' else 10,
                                         announce=False, preview=False)
                    self._update_setting_display(cursor, self._settings_items(), selected,
                                                 self._setting_value(options[selected][0]))
                    if self.cue_volume != old_volume or self.audio_output != old_audio_output:
                        self.preview_cue_volume()
                    continue
                if key in ('\r', '\n'):
                    choice = options[selected][0]
                elif key in {'1', '2', '3', '4'}:
                    choice = key
                    selected = next(index for index, (option, _) in enumerate(options)
                                    if option == choice)
                else:
                    continue
                if choice == '0':
                    return
                if choice in ('1', '3'):
                    self._adjust_setting(choice, 10, announce=False)
                    self._update_setting_display(cursor, self._settings_items(), selected,
                                                 self._setting_value(choice))
                else:
                    self.stop_entry_speech()
                    cursor.finish()
                    if choice == '2':
                        self.select_audio_output()
                    elif choice == '4':
                        self.cue_volume_menu()
                    show()
        finally:
            cursor.finish()
            self.stop_entry_speech()

    def _setting_value(self, option):
        return {'1': 'On' if self.panned_cues else 'Off',
                '2': self.audio_output or 'System default',
                '3': 'On' if self.handoff_sound else 'Off',
                '4': f'{self.cue_volume} percent'}.get(option)

    def _update_setting_display(self, cursor, items, selected, value):
        if self.windowed:
            cursor.update(items, selected, spoken_value=value)
        else:
            cursor.update(items, selected, advance_caret=True)
            if value is not None:
                self.announce_control(value + '.')

    def _settings_items(self):
        return [
            ('1', 'Cue panning ' + ('on' if self.panned_cues else 'off')),
            ('2', 'Audio device ' + (self.audio_output or 'System default')),
            ('3', 'Handoff sound ' + ('on' if self.handoff_sound else 'off')),
            ('4', f'Cue volume {self.cue_volume} percent'),
            ('0', 'Back'),
        ]

    def _adjust_setting(self, option, delta, announce=True, preview=True):
        if option == '1':
            self.panned_cues = not self.panned_cues
            self.save_settings()
            if announce: self.speech.say('Cue panning ' + ('on.' if self.panned_cues else 'off.'))
        elif option == '3':
            self.handoff_sound = not self.handoff_sound
            self.save_settings()
            if announce: self.speech.say('Handoff sound ' + ('on.' if self.handoff_sound else 'off.'))
        elif option == '4':
            new_volume = max(0, min(200, self.cue_volume + delta))
            if new_volume != self.cue_volume:
                self.cue_volume = new_volume
                self.save_settings()
                if announce: self.speech.say(f'Cue volume {self.cue_volume} percent.')
                if preview: self.preview_cue_volume()
        elif option == '2':
            self.close_cue_preview()
            choices = self.audio_choices()
            current = choices.index(self.audio_output) if self.audio_output in choices else 0
            self.audio_output = choices[(current + (1 if delta > 0 else -1)) % len(choices)]
            self.save_settings()
            if announce: self.speech.say('Audio device ' + (self.audio_output or 'System default') + '.')

    def cue_volume_menu(self):
        cursor = self.menu_surface()
        instructions = 'Arrows change volume by 10 percent. 100 percent is the original volume. 0 or Escape returns.'
        def items():
            return [('4', f'Cue volume {self.cue_volume} percent'), ('0', 'Back')]
        selected = 0
        cursor.show('Cue volume', items(), selected, instructions)
        self.announce_control('Cue volume. ' + instructions + ' ' + self.spoken_menu_item(items(), 0))
        try:
            while True:
                key = self.read_key()
                if key in ('0', '\x1b') or (key in ('\r', '\n') and selected == 1):
                    return
                if key.startswith('select:'):
                    selected = int(key.split(':', 1)[1])
                    cursor.move(selected)
                    continue
                if key in ('up', 'right', 'down', 'left'):
                    selected = 0
                    old_volume = self.cue_volume
                    self._adjust_setting('4', 10 if key in ('up', 'right') else -10, announce=False, preview=False)
                    self._update_setting_display(cursor, items(), 0, self._setting_value('4'))
                    if self.cue_volume != old_volume: self.preview_cue_volume()
        finally:
            cursor.finish()
            self.stop_entry_speech()

    @staticmethod
    def _main_items():
        return [('1', 'Play'), ('2', 'Learn sounds'), ('3', 'Settings'), ('0', 'Exit')]

    def ensure_setup(self):
        """Run a read-only installation check before the first Play launch."""
        if self._setup_checked:
            return True
        from launcher_setup import check_setup

        errors = check_setup(ROOT)
        if errors:
            self.speech.say('Setup needs attention. ' + ' '.join(errors))
            return False
        self._setup_checked = True
        return True

    def _resolved_audio_output(self):
        import audio_devices

        try:
            return audio_devices.resolve_preference(self.audio_output)
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(f'Could not identify the current audio device: {exc}') from exc

    def run_accessible(self):
        cursor = self.menu_surface()
        options = self._main_items()
        selected = 0
        instructions = 'Arrows to move, Enter or number keys select.'
        def show():
            cursor.show('Parappa Access', options, selected, instructions)
            self.announce_control('Parappa Access. ' + instructions + ' ' +
                                self.spoken_menu_item(options, selected, numbered=True))

        show()
        try:
            while True:
                key = self.read_key()
                if key.startswith('select:'):
                    selected = int(key.split(':', 1)[1])
                    cursor.move(selected)
                    self.announce_control(self.spoken_menu_item(options, selected))
                    continue
                if key in ('up', 'down'):
                    selected = (selected + (-1 if key == 'up' else 1)) % len(options)
                    cursor.move(selected)
                    self.announce_control(self.spoken_menu_item(options, selected))
                    continue
                if key in ('\r', '\n'):
                    choice = options[selected][0]
                elif key in {'0', '1', '2', '3'}:
                    choice = key
                    selected = next(index for index, (option, _) in enumerate(options)
                                    if option == choice)
                else:
                    continue
                self.stop_entry_speech()
                cursor.finish()
                try:
                    if choice == '0':
                        self.stop_demo()
                        return
                    if choice == '1':
                        self._close_practice_audio()
                        self.close_cue_preview()
                        if not self.ensure_setup():
                            show()
                            continue
                        output_name = self._resolved_audio_output()
                        if not output_name:
                            self.speech.say('Choose an audio device in Settings before playing.')
                            show()
                            continue
                        self.play_duckstation(from_title=True, audio_output=output_name)
                        show()
                    elif choice == '2':
                        self.audition()
                        show()
                    elif choice == '3':
                        self.settings_menu()
                        show()
                except (ImportError, OSError, RuntimeError, ValueError,
                        subprocess.TimeoutExpired) as exc:
                    self.speech.say(str(exc))
                    show()
        finally:
            self._close_practice_audio()
            self.close_cue_preview()
            cursor.finish()
            self.stop_entry_speech()

    def practice_keys(self, sounds=None):
        if sounds is None:
            return self.audition()
        from duckstation_keyboard import LEARN_KEYS
        bindings = LEARN_KEYS
        keys = list(bindings)
        items = [(key.upper(), name) for key, (name, _) in bindings.items()] + [
            ('', 'Handoff'), ('0', 'Return to main menu')]
        selected = 0
        cursor = self.menu_surface()
        instructions = 'Arrows select. Enter or letter keys play. Escape or 0 returns.'
        cursor.show('Learn sounds', items, selected, instructions)
        self.announce_control('Learn sounds. ' + instructions + ' ' + self.spoken_menu_item(items, selected, numbered=True))
        try:
            start = getattr(sounds, 'start', None)
            if start is not None:
                start()
            while True:
                key = self.read_key()
                if key in ('0', '\x1b'):
                    return
                if key in bindings:
                    if not sounds.play(bindings[key][1]).get('result'):
                        self.announce_entry('Sound playback failed.')
                    continue
                if key.startswith('select:'):
                    selected = int(key.split(':', 1)[1])
                elif key in ('up', 'down'):
                    selected = (selected + (-1 if key == 'up' else 1)) % len(items)
                elif key not in ('\r', '\n'):
                    continue
                if key not in ('\r', '\n'):
                    cursor.move(selected)
                    self.announce_control(items[selected][1] + '.')
                    continue
                if selected == len(items) - 1:
                    return
                result = (sounds.play_handoff() if selected == len(keys)
                          else sounds.play(bindings[keys[selected]][1]))
                if not result.get('result'):
                    self.announce_entry('Sound playback failed.')
        finally:
            sounds.stop()
            cursor.finish()
            self.stop_entry_speech()

    @staticmethod
    def _checkpoint_session_label(manifest_path):
        session = Path(manifest_path).parent.name
        try:
            return datetime.strptime(session, '%Y%m%dT%H%M%SZ').strftime('%Y-%m-%d %H:%M:%S UTC')
        except ValueError:
            return session

    def choose_duckstation_checkpoint(self):
        """List verified campaign states and return the selected manifest path."""
        errors = []
        checkpoints = list_checkpoints(ROOT, errors=errors)
        for error in errors:
            print(f"Skipping invalid checkpoint {error['path']}: {error['error']}", flush=True)
        if not checkpoints:
            self.speech.say('No verified DuckStation checkpoints are available. 0 Cancel.')
            return None

        choices = []
        for number, checkpoint in enumerate(checkpoints, 1):
            session = self._checkpoint_session_label(checkpoint['manifest_path'])
            label = f"Stage {checkpoint['stage']} {checkpoint['kind']}, {session}"
            choices.append((str(number), checkpoint, label))
        print('DuckStation checkpoints.', flush=True)
        for number, _, label in choices:
            print(f'{number}. {label}', flush=True)
        print('0. Cancel', flush=True)

        while True:
            choice = input('Checkpoint number (0 cancel): ').strip()
            if choice == '0':
                self.speech.say('Cancelled.')
                return None
            selected = next((checkpoint for number, checkpoint, _ in choices
                             if choice == number), None)
            if selected is not None:
                self.speech.say(f"Stage {selected['stage']} {selected['kind']} selected.")
                return selected['manifest_path']
            self.speech.say('Enter a listed number, or 0 to cancel.')

    def play_duckstation(self, from_title=False, audio_output=None, checkpoint=None):
        self._close_practice_audio()
        self.stop_demo()
        output_name = audio_output or self._resolved_audio_output()
        if not output_name:
            self.speech.say('Choose an audio device in Settings before playing.')
            return
        (LOGS / 'demo-panning.txt').write_text('on' if self.panned_cues else 'off', encoding='ascii')
        args = [sys.executable, str(ROOT / 'scripts' / 'duckstation-compare.py'),
                '--audio-output', output_name, '--auto-controller',
                '--cue-volume', str(self.cue_volume)]
        if checkpoint is None:
            args.append('--redux-memory-cards')
        else:
            args.extend(['--checkpoint', str(checkpoint), '--auto-start'])
        if self.handoff_sound:
            args.append('--handoff-sound')
        if from_title and checkpoint is None:
            args.extend(['--from-boot', '--auto-start'])
        if not self.game_speech_enabled:
            args.append('--no-speech')
        self.speech.stop()
        if self.windowed:
            # Normal Play is already auto-started: keep diagnostic output out of
            # NVDA's console focus and retain it in a fresh session log instead.
            launch_logs = LOGS / 'launcher-runs'
            launch_logs.mkdir(parents=True, exist_ok=True)
            path = launch_logs / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '.log')
            with path.open('x', encoding='utf-8') as output:
                result = subprocess.run(args, cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            result = subprocess.run(args, cwd=ROOT)
        if result.returncode:
            self.speech.say('DuckStation ended with an error. See logs/launcher-runs and logs/duck-prepare files.')

    def run_developer(self):
        help_text = ('PaRappa accessibility. 1 choose a stage checkpoint. '
                     '2 pause or resume. 3 learn sounds. 4 controls. '
                     '5 DuckStation Stage 1. 6 toggle cue panning. '
                     '7 DuckStation from boot. 8 Redux from boot. '
                     '9 DuckStation checkpoints. '
                     '0 quit. Type a number and press Enter.')
        self.speech.say(help_text)
        try:
            while True:
                choice = input('Choice: ').strip()
                try:
                    if choice == '0':
                        self.stop_demo()
                        return
                    if choice == '1':
                        stage = self.choose_checkpoint()
                        if stage is not None:
                            self.play(native=True, checkpoint=stage)
                    elif choice == '8':
                        self.play(native=True)
                    elif choice in ('5', '7'):
                        self.play_duckstation(from_title=choice == '7')
                        self.speech.say(help_text)
                    elif choice == '9':
                        manifest_path = self.choose_duckstation_checkpoint()
                        if manifest_path is not None:
                            self.play_duckstation(checkpoint=manifest_path)
                        self.speech.say(help_text)
                    elif choice == '2':
                        if not self.running():
                            self.speech.say('Demo is stopped. ' + help_text)
                        elif self.paused:
                            self.speech.stop()
                            self.command('resume')
                            self.paused = False
                        else:
                            self.command('pause')
                            self.paused = True
                            self.speech.say('Paused. ' + help_text)
                    elif choice == '3':
                        self.audition()
                        self.speech.say(help_text)
                    elif choice == '4':
                        if self.running() and not self.paused:
                            self.command('pause')
                            self.paused = True
                        self.speech.say('With no gamepad connected, default keyboard controls '
                                        'in PCSX Redux are: D is Circle. '
                                        'X is X. Z is Square. S is Triangle. Q is L1. R is R1. '
                                        'E Score. H Menu controls. Enter Start. '
                                        'During a round, Start opens Retry or Leave; it does not resume a paused round. '
                                        'The emulator must have keyboard focus. Repeat the '
                                        'teacher on your response; there are no added response cues.')
                    elif choice == '6':
                        if self.running() and not self.paused:
                            self.command('pause')
                            self.paused = True
                        self.panned_cues = not self.panned_cues
                        self.save_settings()
                        self.speech.say('Cue panning ' + ('on' if self.panned_cues else 'off') +
                                        '. Choose 3 to practice or 1 to select a checkpoint with this setting.')
                    elif not self.running() or self.paused:
                        self.speech.say(help_text)
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    # Do not narrate over a running rhythm demonstration/response.
                    if self.running() and not self.paused:
                        print(str(exc), flush=True)
                    else:
                        self.speech.say(str(exc))
        finally:
            self._close_practice_audio()
            self.speech.stop()
            try:
                self.stop_demo()
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                print('Could not close the demo automatically:', exc)

    def run(self, developer=None):
        # Existing diagnostic subclasses such as TimingMenu called run() before
        # the accessible front menu existed. Preserve their command workflow;
        # the actual launcher passes an explicit mode from its CLI flag.
        if developer is None:
            developer = type(self) is not Menu
        if developer:
            return self.run_developer()
        return self.run_accessible()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-speech', action='store_true')
    parser.add_argument('--speech-test', action='store_true')
    parser.add_argument('--console-menu', action='store_true',
                        help='Use the older console menu instead of the Windows window.')
    parser.add_argument('--developer-menu', action='store_true',
                        help='Open the legacy checkpoint and diagnostics menu.')
    args = parser.parse_args(argv)
    # Console menus are read by the user's screen reader, once. Direct Prism
    # speech remains separate for events while the emulator has focus.
    speech = Speech(args.speech_test and not args.no_speech)
    try:
        if args.speech_test:
            speech.say('Prism speech test. PaRappa menu speech is ready.')
            input('Press Enter to finish the speech test.')
        else:
            Menu(speech, game_speech_enabled=not args.no_speech,
                 windowed=not (args.console_menu or args.developer_menu)).run(developer=args.developer_menu)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        speech.stop()
        window = sys.modules.get('window_menu')
        if window is not None:
            window.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
