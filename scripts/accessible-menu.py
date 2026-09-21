"""Prism-spoken launcher for the local PaRappa accessibility project."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import msvcrt
import subprocess
import sys
import threading
import time
import launcher_settings


def list_checkpoints(*args, **kwargs):
    if (ROOT / 'public-build.json').is_file():
        raise RuntimeError('Checkpoint tools are only available in the source checkout.')
    sys.path.insert(0, str(ROOT / 'developer'))
    from duckstation_checkpoint_catalog import list_checkpoints as enumerate_checkpoints
    return enumerate_checkpoints(*args, **kwargs)

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / 'logs'
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

    def say(self, text, interrupt=True):
        """Speak text; interrupt=False queues it after what is already speaking."""
        with self.lock:
            if self.backend:
                try:
                    self.backend.speak(text, interrupt=interrupt)
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
        self.preferences_path = Path(preferences_path or launcher_settings.SETTINGS_PATH)
        self.legacy_panning_path = Path(legacy_panning_path or launcher_settings.LEGACY_PANNING_PATH)
        preferences = launcher_settings.load_settings(self.preferences_path, self.legacy_panning_path)
        self.panned_cues = preferences['panned_cues']
        self.audio_output = preferences['audio_output']
        self.handoff_sound = preferences['handoff_sound']
        self.cue_volume = preferences['cue_volume']
        self.diagnostics = preferences.get('diagnostics', False)
        self.subtitles = preferences.get('subtitles', False)
        self.lyrics = preferences.get('lyrics', False)
        self._setup_checked = False
        self._practice_audio = []
        LOGS.mkdir(exist_ok=True)

    def save_settings(self):
        launcher_settings.save_settings({
            'panned_cues': self.panned_cues,
            'audio_output': self.audio_output,
            'handoff_sound': self.handoff_sound,
            'cue_volume': self.cue_volume,
            'diagnostics': self.diagnostics,
            'subtitles': self.subtitles,
            'lyrics': self.lyrics,
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


    def _close_practice_audio(self):
        for sounds in self._practice_audio:
            sounds.close()
        self._practice_audio.clear()

    def audition(self):
        self.close_cue_preview()
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
                    if options[selected][0] in ('8', '0'):
                        continue
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
                elif key in {'1', '2', '3', '4', '5', '6', '7', '8'}:
                    choice = key
                    selected = next(index for index, (option, _) in enumerate(options)
                                    if option == choice)
                else:
                    continue
                if choice == '0':
                    return
                if choice in ('1', '3', '5', '6', '7'):
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
                    elif choice == '8':
                        self.close_cue_preview()
                        self.change_game_or_bios()
                    show()
        finally:
            cursor.finish()
            self.stop_entry_speech()

    def _setting_value(self, option):
        return {'1': 'On' if self.panned_cues else 'Off',
                '2': self.audio_output or 'System default',
                '3': 'On' if self.handoff_sound else 'Off',
                '4': f'{self.cue_volume} percent',
                '5': 'On' if self.diagnostics else 'Off',
                '6': 'On' if self.subtitles else 'Off',
                '7': 'On' if self.lyrics else 'Off'}.get(option)

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
            ('5', 'Diagnostic logging ' + ('on' if self.diagnostics else 'off')),
            ('6', 'Spoken subtitles ' + ('on' if self.subtitles else 'off')),
            ('7', 'Spoken lyrics ' + ('on' if self.lyrics else 'off')),
            ('8', 'Change game or BIOS'),
            ('0', 'Back'),
        ]

    def change_game_or_bios(self):
        from launcher_first_run import prepare
        cursor = self.menu_surface()
        items = [('1', 'Change game'), ('2', 'Change BIOS'), ('0', 'Back')]
        selected = 0
        instructions = 'Arrows to move, Enter or number keys select.'
        def show():
            cursor.show('Change game or BIOS', items, selected, instructions)
            self.announce_control('Change game or BIOS. ' + instructions + ' ' +
                                  self.spoken_menu_item(items, selected, numbered=True))
        show()
        try:
            while True:
                key = self.read_key()
                if key in ('0', '\x1b'):
                    return
                if key in ('up', 'down') or key.startswith('select:'):
                    selected = (int(key.split(':', 1)[1]) if key.startswith('select:') else
                                (selected + (-1 if key == 'up' else 1)) % len(items))
                    cursor.move(selected)
                    self.announce_control(self.spoken_menu_item(items, selected))
                    continue
                choice = items[selected][0] if key in ('\r', '\n') else key
                if choice == '0':
                    return
                if choice not in ('1', '2'):
                    continue
                selected = int(choice) - 1
                self.stop_entry_speech()
                cursor.finish()
                try:
                    if prepare(ROOT, change='game' if choice == '1' else 'bios'):
                        self._setup_checked = False
                except (OSError, RuntimeError, ValueError) as error:
                    self.speech.say(str(error))
                show()
        finally:
            cursor.finish()
            self.stop_entry_speech()

    def _adjust_setting(self, option, delta, announce=True, preview=True):
        if option == '5':
            self.diagnostics = not self.diagnostics
            self.save_settings()
            if announce: self.speech.say('On.' if self.diagnostics else 'Off.')
        elif option == '1':
            self.panned_cues = not self.panned_cues
            self.save_settings()
            if announce: self.speech.say('Cue panning ' + ('on.' if self.panned_cues else 'off.'))
        elif option == '3':
            self.handoff_sound = not self.handoff_sound
            self.save_settings()
            if announce: self.speech.say('Handoff sound ' + ('on.' if self.handoff_sound else 'off.'))
        elif option == '6':
            # Same preference the U key toggles in game.
            self.subtitles = not self.subtitles
            self.save_settings()
            if announce: self.speech.say('Spoken subtitles ' + ('on.' if self.subtitles else 'off.'))
        elif option == '7':
            # Same preference the Y key toggles in game.
            self.lyrics = not self.lyrics
            self.save_settings()
            if announce: self.speech.say('Spoken lyrics ' + ('on.' if self.lyrics else 'off.'))
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

    def ensure_setup(self, first_launch=False):
        """Verify the installation and prepare it when a supported UI needs it."""
        if self._setup_checked:
            return True
        from launcher_setup import check_setup

        errors = check_setup(ROOT)
        if errors and (first_launch or (ROOT / 'public-build.json').is_file()):
            from launcher_first_run import prepare
            if not prepare(ROOT):
                return False
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
        # The player UI checks setup before showing its main menu. Ready
        # installations pass through without dialogs; cancel exits cleanly.
        if self.windowed:
            try:
                if not self.ensure_setup(first_launch=True):
                    return
            except Exception as exc:
                self.speech.say('Setup needs attention. ' + str(exc))
                return
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
        output_name = audio_output or self._resolved_audio_output()
        if not output_name:
            self.speech.say('Choose an audio device in Settings before playing.')
            return
        (LOGS / 'demo-panning.txt').write_text('on' if self.panned_cues else 'off', encoding='ascii')
        args = [sys.executable, str(ROOT / 'scripts' / 'duckstation-compare.py'),
                '--audio-output', output_name, '--auto-controller',
                '--cue-volume', str(self.cue_volume)]
        if self.diagnostics:
            args.append('--diagnostics')
        if checkpoint is None:
            args.append('--saved-memory-cards')
        elif checkpoint is not None:
            args.extend(['--checkpoint', str(checkpoint), '--auto-start'])
        if self.handoff_sound:
            args.append('--handoff-sound')
        if from_title and checkpoint is None:
            args.extend(['--from-boot', '--auto-start'])
        if not self.game_speech_enabled:
            args.append('--no-speech')
        self.speech.stop()
        if self.windowed and self.diagnostics:
            # Normal Play is already auto-started: keep diagnostic output out of
            # NVDA's console focus and retain it in a fresh session log instead.
            launch_logs = LOGS / 'launcher-runs'
            launch_logs.mkdir(parents=True, exist_ok=True)
            path = launch_logs / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '.log')
            with path.open('x', encoding='utf-8') as output:
                result = subprocess.run(args, cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW)
        elif self.windowed:
            result = subprocess.run(args, cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            result = subprocess.run(args, cwd=ROOT)
        if result.returncode == 3:
            self.speech.say('The selected image could not be verified as the supported US '
                            'PaRappa version, SCUS-94183. Check that it is a complete, '
                            'unmodified image. Accessibility playback was not started.')
        elif result.returncode:
            detail = ' See logs/launcher-runs and logs/duck-prepare files.' if self.diagnostics else ' Enable Diagnostic logging in Settings to record details for a retry.'
            self.speech.say('DuckStation ended with an error.' + detail)

    def run_developer(self):
        print('DuckStation testing. 1 Boot. 2 Checkpoint. 3 Learn sounds. 0 Exit.')
        try:
            while True:
                choice = input('Choice: ').strip()
                if choice == '0':
                    return
                if choice == '1':
                    self.play_duckstation(from_title=True)
                elif choice == '2':
                    manifest = self.choose_duckstation_checkpoint()
                    if manifest:
                        self.play_duckstation(checkpoint=manifest)
                elif choice == '3':
                    self.audition()
        finally:
            self._close_practice_audio()
            self.close_cue_preview()

    def run(self, developer=False):
        return self.run_developer() if developer else self.run_accessible()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-speech', action='store_true')
    parser.add_argument('--speech-test', action='store_true')
    parser.add_argument('--console-menu', action='store_true',
                        help='Use the older console menu instead of the Windows window.')
    parser.add_argument('--developer-menu', action='store_true',
                        help='Open DuckStation developer tools (source checkout only).')
    args = parser.parse_args(argv)
    if (args.developer_menu or args.console_menu or args.speech_test) and (ROOT / 'public-build.json').is_file():
        parser.error('Console and developer tools are available only in the source checkout.')
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
