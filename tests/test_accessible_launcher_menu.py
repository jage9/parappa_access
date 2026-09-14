import _bootstrap
import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import Mock, patch

import launcher_settings


ROOT = Path(__file__).resolve().parents[1]
MENU_PATH = ROOT / "scripts" / "accessible-menu.py"
SPEC = importlib.util.spec_from_file_location("accessible_menu_tests", MENU_PATH)
accessible_menu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(accessible_menu)


class FakeSpeech:
    def __init__(self):
        self.messages = []
        self.backend = None

    def say(self, text):
        self.messages.append(text)

    def stop(self):
        pass


class LauncherSettingsTests(unittest.TestCase):
    def test_first_run_migrates_legacy_pan_and_saves_default_output(self):
        with TemporaryDirectory() as folder:
            settings = Path(folder) / "accessibility-settings.json"
            legacy = Path(folder) / "demo-panning.txt"
            legacy.write_text("off", encoding="ascii")

            loaded = launcher_settings.load_settings(settings, legacy)

            self.assertEqual(loaded, {"panned_cues": False, "audio_output": None,
                                      "handoff_sound": True, "cue_volume": 100, "diagnostics": False})
            self.assertEqual(launcher_settings.load_settings(settings, legacy), loaded)
            self.assertEqual(settings.read_text(encoding="utf-8").count('"schema_version": 1'), 1)

    def test_malformed_existing_settings_are_left_untouched(self):
        with TemporaryDirectory() as folder:
            settings = Path(folder) / "accessibility-settings.json"
            settings.write_text("{bad json", encoding="utf-8")

            loaded = launcher_settings.load_settings(settings, Path(folder) / "missing-pan.txt")

            self.assertEqual(loaded, {"panned_cues": True, "audio_output": None,
                                      "handoff_sound": True, "cue_volume": 100, "diagnostics": False})
            self.assertEqual(settings.read_text(encoding="utf-8"), "{bad json")

    def test_save_and_reload_panning_and_exact_audio_name(self):
        with TemporaryDirectory() as folder:
            settings = Path(folder) / "accessibility-settings.json"
            expected = {"panned_cues": False, "audio_output": "USB Headphones",
                        "handoff_sound": False, "cue_volume": 130, "diagnostics": False}

            launcher_settings.save_settings(expected, settings)

            self.assertEqual(launcher_settings.load_settings(settings), expected)

    def test_existing_settings_without_handoff_sound_default_to_on(self):
        with TemporaryDirectory() as folder:
            settings = Path(folder) / "accessibility-settings.json"
            settings.write_text(
                '{"schema_version": 1, "panned_cues": false, "audio_output": null}\n',
                encoding="utf-8")

            loaded = launcher_settings.load_settings(settings)

            self.assertEqual(loaded, {"panned_cues": False, "audio_output": None,
                                      "handoff_sound": True, "cue_volume": 100, "diagnostics": False})
            self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["schema_version"], 1)


class AccessibleMenuTests(unittest.TestCase):
    def setUp(self):
        # Menu navigation tests must not open real first-run dialogs on CI.
        setup = patch('launcher_setup.check_setup', return_value=[])
        setup.start()
        self.addCleanup(setup.stop)
        outputs = patch('audio_devices.list_outputs', return_value=[])
        outputs.start()
        self.addCleanup(outputs.stop)

    def make_menu(self, folder):
        menu = accessible_menu.Menu(
            FakeSpeech(),
            preferences_path=Path(folder) / "accessibility-settings.json",
            legacy_panning_path=Path(folder) / "missing-pan.txt",
        )
        # Navigation tests start with the optional sound explicitly disabled.
        menu.handoff_sound = False
        menu._entry_speech = Mock()
        menu.prepare_cue_preview = Mock()
        menu.preview_cue_volume = Mock()
        menu.close_cue_preview = Mock()
        return menu

    def test_settings_routes_to_file_selection_and_rechecks_setup(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu._setup_checked = True
            with patch.object(menu, 'menu_surface', return_value=Mock()), \
                    patch.object(menu, 'read_key', side_effect=('6', 'down', '\r', '0', '0')), \
                    patch('launcher_first_run.prepare', return_value=True) as prepare:
                menu.settings_menu()
            prepare.assert_called_once_with(accessible_menu.ROOT, change='bios')
            self.assertFalse(menu._setup_checked)

    def test_cancel_game_selection_retains_setup_cache(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu._setup_checked = True
            with patch.object(menu, 'menu_surface', return_value=Mock()), \
                    patch.object(menu, 'read_key', side_effect=('1', '0')), \
                    patch('launcher_first_run.prepare', return_value=False) as prepare:
                menu.change_game_or_bios()
            prepare.assert_called_once_with(accessible_menu.ROOT, change='game')
            self.assertTrue(menu._setup_checked)

    def test_main_menu_uses_single_key_play_and_exit(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.ensure_setup = Mock(return_value=True)
            menu._resolved_audio_output = Mock(return_value="USB Headphones")
            menu.play_duckstation = Mock()
            output = StringIO()
            with patch.object(menu, "read_key", side_effect=("1", "0")), \
                    redirect_stdout(output):
                menu.run()

            menu.play_duckstation.assert_called_once_with(
                from_title=True, audio_output="USB Headphones")
            menu.ensure_setup.assert_called_once_with()
            self.assertEqual(output.getvalue().splitlines()[1:5], [
                '1. Play', '2. Learn sounds', '3. Settings', '0. Exit',
            ])
            self.assertEqual(menu.speech.messages, [])

    def test_windowed_startup_checks_setup_before_showing_main_menu(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.windowed = True
            events = []
            menu.ensure_setup = Mock(side_effect=lambda **kwargs: (events.append('setup'), True)[1])
            cursor = Mock()
            cursor.show.side_effect = lambda *args: events.append('menu')
            menu.menu_surface = Mock(side_effect=lambda: (events.append('surface'), cursor)[1])
            with patch.object(menu, 'read_key', return_value='0'):
                menu.run()

            self.assertEqual(events, ['setup', 'surface', 'menu'])
            menu.ensure_setup.assert_called_once_with(first_launch=True)

    def test_cancelled_windowed_startup_exits_without_opening_menu(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.windowed = True
            menu.ensure_setup = Mock(return_value=False)
            menu.menu_surface = Mock()
            menu.play_duckstation = Mock()

            menu.run()

            menu.ensure_setup.assert_called_once_with(first_launch=True)
            menu.menu_surface.assert_not_called()
            menu.play_duckstation.assert_not_called()

    def test_configured_windowed_startup_skips_first_run_dialogs(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            with patch.object(accessible_menu, 'ROOT', Path(folder)), \
                    patch('launcher_setup.check_setup', return_value=[]) as check_setup, \
                    patch('launcher_first_run.prepare') as prepare:
                self.assertTrue(menu.ensure_setup(first_launch=True))

            check_setup.assert_called_once_with(Path(folder))
            prepare.assert_not_called()

    def test_main_menu_arrows_select_enter_and_numbers_still_activate(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.audition = Mock()
            output = StringIO()
            with patch.object(menu, 'read_key', side_effect=('down', '\r', '0')), \
                    patch('console_menu_cursor.ConsoleMenuCursor.move') as move, \
                    redirect_stdout(output):
                menu.run()

            menu.audition.assert_called_once_with()
            self.assertEqual(menu.speech.messages, [])
            move.assert_called_once_with(1)
            self.assertEqual(output.getvalue().splitlines().count('Parappa Access'), 2)
            self.assertEqual(output.getvalue().splitlines().count('2. Learn sounds'), 2)

    def test_console_menu_keeps_game_speech_enabled(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            self.assertIsNone(menu.speech.backend)
            menu.game_speech_enabled = True
            menu.cue_volume = 130
            with patch.object(accessible_menu, 'LOGS', Path(folder)), \
                    patch.object(accessible_menu.subprocess, 'run') as run:
                run.return_value.returncode = 0
                menu.play_duckstation(from_title=True, audio_output='USB Headphones')
            self.assertNotIn('--no-speech', run.call_args.args[0])
            self.assertNotIn('--handoff-sound', run.call_args.args[0])
            self.assertIn('--auto-start', run.call_args.args[0])
            args = run.call_args.args[0]
            self.assertEqual(args[args.index('--cue-volume') + 1], '130')
            self.assertIn('--auto-controller', run.call_args.args[0])

    def test_duckstation_passes_handoff_flag_only_when_enabled(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.handoff_sound = True
            with patch.object(accessible_menu, 'LOGS', Path(folder)), \
                    patch.object(accessible_menu.subprocess, 'run') as run:
                run.return_value.returncode = 0
                menu.play_duckstation(audio_output='USB Headphones')

            args = run.call_args.args[0]
            self.assertIn('--handoff-sound', args)
            self.assertIn('--no-speech', args)

    def test_duckstation_checkpoint_launch_preserves_accessibility_args_without_cards_or_boot(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.handoff_sound = True
            menu.game_speech_enabled = False
            manifest = Path(folder) / 'checkpoint-stage4-entry.json'
            with patch.object(accessible_menu, 'LOGS', Path(folder)), \
                    patch.object(accessible_menu.subprocess, 'run') as run:
                run.return_value.returncode = 0
                menu.play_duckstation(from_title=True, audio_output='USB Headphones',
                                      checkpoint=manifest)

            args = run.call_args.args[0]
            self.assertIn('--checkpoint', args)
            self.assertEqual(args[args.index('--checkpoint') + 1], str(manifest))
            self.assertEqual(args.count('--auto-start'), 1)
            self.assertIn('--auto-controller', args)

            self.assertIn('--audio-output', args)
            self.assertEqual(args[args.index('--audio-output') + 1], 'USB Headphones')
            self.assertIn('--handoff-sound', args)
            self.assertIn('--no-speech', args)
            self.assertNotIn('--from-boot', args)
            self.assertNotIn('--saved-memory-cards', args)

    def test_main_and_settings_announce_entry_once_without_navigation_speech(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu._entry_speech = Mock()
            menu.prepare_cue_preview = Mock()
            menu.close_cue_preview = Mock()
            output = StringIO()
            # Main -> Settings, move twice, change handoff, Back -> Main -> Exit.
            with patch.object(menu, 'read_key', side_effect=(
                    '3', 'down', 'down', 'right', '0', '0')), redirect_stdout(output):
                menu.run()
            self.assertEqual([call.args[0] for call in menu._entry_speech.say.call_args_list], [
                'Parappa Access. Arrows to move, Enter or number keys select. 1. Play.',
                'Settings. Arrows to move, Enter or number keys select. Left and right change settings. 1. Cue panning on.',
                '2. Audio device System default.',
                '3. Handoff sound off.',
                'On.',
                'Parappa Access. Arrows to move, Enter or number keys select. 3. Settings.',
            ])
            self.assertTrue(menu.handoff_sound)
            self.assertEqual(menu.speech.messages, [])
            self.assertNotIn('Parappa Access. Arrows', output.getvalue())

    def test_checkpoint_picker_lists_session_and_cancel_returns_none(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            manifest = Path(folder) / '20260913T021212Z' / 'checkpoint-stage2-clear.json'
            checkpoint = {'stage': 2, 'kind': 'clear', 'path': str(manifest.with_suffix('.sav')),
                          'manifest_path': str(manifest)}
            output = StringIO()
            with patch.object(accessible_menu, 'list_checkpoints', return_value=[checkpoint]) as catalog, \
                    patch('builtins.input', return_value='0'), redirect_stdout(output):
                selected = menu.choose_duckstation_checkpoint()

            catalog.assert_called_once()
            self.assertIsNone(selected)
            self.assertEqual(output.getvalue().splitlines(), [
                'DuckStation checkpoints.',
                '1. Stage 2 clear, 2026-09-13 02:12:12 UTC',
                '0. Cancel',
            ])
            self.assertFalse(any('DuckStation checkpoints' in text
                                 for text in menu.speech.messages))
            self.assertEqual(menu.speech.messages[-1], 'Cancelled.')

    def test_developer_checkpoint_launches_selected_manifest(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            manifest = Path(folder) / '20260913T021212Z' / 'checkpoint-stage6-ending.json'
            checkpoint = {'stage': 6, 'kind': 'ending', 'path': str(manifest.with_suffix('.sav')),
                          'manifest_path': str(manifest)}
            menu.play_duckstation = Mock()
            with patch.object(accessible_menu, 'list_checkpoints', return_value=[checkpoint]), \
                    patch('builtins.input', side_effect=('2', '1', '0')), \
                    redirect_stdout(StringIO()):
                menu.run_developer()

            menu.play_duckstation.assert_called_once_with(checkpoint=str(manifest))

    def test_developer_mode_is_explicit(self):
        class DiagnosticMenu(accessible_menu.Menu):
            def run_developer(self):
                return "developer menu"

        with TemporaryDirectory() as folder:
            menu = DiagnosticMenu(FakeSpeech(),
                                  preferences_path=Path(folder) / "settings.json",
                                  legacy_panning_path=Path(folder) / "old.txt")
            self.assertEqual(menu.run(developer=True), "developer menu")
            menu.run_accessible = Mock(return_value="accessible menu")
            self.assertEqual(menu.run(developer=False), "accessible menu")

    def test_settings_pan_toggle_names_setting_and_persists(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            with patch.object(menu, "read_key", side_effect=("1", "0")):
                menu.settings_menu()

            self.assertFalse(menu.panned_cues)
            self.assertEqual(menu.speech.messages, [])
            self.assertFalse(launcher_settings.load_settings(menu.preferences_path)["panned_cues"])
            menu.audio_output = "USB Headphones"
            output = StringIO()
            with patch.object(menu, "read_key", return_value="0"), \
                    redirect_stdout(output):
                menu.settings_menu()
            self.assertEqual(output.getvalue().splitlines()[:8], [
                'Settings', '1. Cue panning off', '2. Audio device USB Headphones',
                '3. Handoff sound off', '4. Cue volume 100 percent', '5. Diagnostic logging off', '6. Change game or BIOS', '0. Back',
            ])

    def test_settings_entry_includes_values_and_handoff_toggle_names_setting(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            output = StringIO()
            with patch.object(menu, "read_key", side_effect=("3", "0")), \
                    redirect_stdout(output):
                menu.settings_menu()

            self.assertTrue(menu.handoff_sound)
            self.assertEqual(menu.speech.messages, [])
            self.assertEqual(output.getvalue().splitlines()[:8], [
                'Settings', '1. Cue panning on', '2. Audio device System default',
                '3. Handoff sound off', '4. Cue volume 100 percent', '5. Diagnostic logging off', '6. Change game or BIOS', '0. Back',
            ])
            self.assertTrue(launcher_settings.load_settings(menu.preferences_path)["handoff_sound"])

    def test_settings_entry_does_not_wait_for_audio_device_enumeration(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            with patch('audio_devices.list_outputs') as outputs, \
                    patch.object(menu, 'read_key', return_value='0'), \
                    redirect_stdout(StringIO()):
                menu.settings_menu()
            outputs.assert_not_called()

    def test_audio_picker_persists_the_selected_exact_name(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            output = type("Output", (), {"name": "USB Headphones"})()
            with patch("audio_devices.list_outputs", return_value=[output]), \
                    patch("audio_devices.current_device", return_value="Speakers"), \
                    patch.object(menu, 'read_key', side_effect=('2', '\r')):
                self.assertTrue(menu.select_audio_output())

            self.assertEqual(menu.audio_output, "USB Headphones")
            self.assertEqual(launcher_settings.load_settings(menu.preferences_path)["audio_output"],
                             "USB Headphones")
            self.assertEqual(menu._entry_speech.say.call_args.args[0], "Audio device USB Headphones.")

    def test_audio_picker_arrows_and_multi_digit_selection(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            devices = [type('Output', (), {'name': f'Device {index}'})()
                       for index in range(1, 11)]
            with patch('audio_devices.list_outputs', return_value=devices), \
                    patch('audio_devices.current_device', return_value='Speakers'), \
                    patch.object(menu, 'read_key', side_effect=('1', '1', '\r')), \
                    redirect_stdout(StringIO()):
                self.assertTrue(menu.select_audio_output())
            self.assertEqual(menu.audio_output, 'Device 10')

            menu.audio_output = None
            with patch('audio_devices.list_outputs', return_value=devices), \
                    patch('audio_devices.current_device', return_value='Speakers'), \
                    patch.object(menu, 'read_key', side_effect=('up', 'up', '\r')), \
                    redirect_stdout(StringIO()):
                self.assertTrue(menu.select_audio_output())
            self.assertEqual(menu.audio_output, 'Device 10')
            self.assertIn('11. Device 10.', [call.args[0] for call in menu._entry_speech.say.call_args_list])

    def test_volume_arrows_persist_and_clamp_at_bounds(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.preview_cue_volume = Mock()
            for initial, keys, expected in ((100, ('up', 'up', 'down', '0'), 110),
                                             (200, ('up', '\x1b'), 200),
                                             (0, ('down', '0'), 0)):
                menu.cue_volume = initial
                menu.save_settings()
                with patch.object(menu, 'read_key', side_effect=keys), \
                        redirect_stdout(StringIO()):
                    menu.cue_volume_menu()
                self.assertEqual(menu.cue_volume, expected)
                self.assertEqual(launcher_settings.load_settings(menu.preferences_path)['cue_volume'], expected)
            self.assertEqual(menu.preview_cue_volume.call_count, 3)
            self.assertIn('110 percent.', [call.args[0] for call in menu._entry_speech.say.call_args_list])

    def test_settings_arrows_toggle_and_adjust_current_setting(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.preview_cue_volume = Mock()
            with patch.object(menu, 'read_key', side_effect=(
                    'right', 'down', 'down', 'right', 'down', 'right', 'left', '0')), \
                    redirect_stdout(StringIO()):
                menu.settings_menu()

            self.assertFalse(menu.panned_cues)
            self.assertTrue(menu.handoff_sound)
            self.assertEqual(menu.cue_volume, 100)
            self.assertEqual(menu.preview_cue_volume.call_count, 2)
            saved = launcher_settings.load_settings(menu.preferences_path)
            self.assertFalse(saved['panned_cues'])
            self.assertTrue(saved['handoff_sound'])
            self.assertEqual(saved['cue_volume'], 100)

    def test_audio_arrows_cycle_cached_system_default_and_devices(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            devices = [type('Output', (), {'name': name})() for name in ('Speakers', 'Headphones')]
            with patch('audio_devices.list_outputs', return_value=devices) as scan, \
                    patch.object(menu, 'read_key', side_effect=(
                        'down', 'right', 'right', 'right', 'left', '0')), redirect_stdout(StringIO()):
                menu.settings_menu()
            scan.assert_called_once()
            self.assertEqual(menu.audio_output, 'Headphones')
            self.assertEqual(menu.preview_cue_volume.call_count, 4)
            spoken = [call.args[0] for call in menu._entry_speech.say.call_args_list]
            self.assertEqual(spoken[1:], ['2. Audio device System default.', 'Speakers.',
                'Headphones.', 'System default.', 'Headphones.'])

    def test_audio_picker_system_default_is_first_and_can_replace_explicit_device(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.audio_output = 'Headphones'
            output = StringIO()
            with patch.object(menu, 'read_key', side_effect=('1', '\r')), redirect_stdout(output):
                self.assertTrue(menu.select_audio_output())
            self.assertIsNone(menu.audio_output)
            self.assertIsNone(launcher_settings.load_settings(menu.preferences_path)['audio_output'])
            self.assertEqual(output.getvalue().splitlines()[1], '1. System default')
            self.assertNotIn('Use configured device', output.getvalue())

    def test_sound_practice_arrows_enter_and_letters_share_selection(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            sounds = Mock()
            sounds.play.return_value = {'result': True}
            with patch.object(menu, 'read_key', side_effect=('down', '\r', 'q', 'up', '0')), \
                    redirect_stdout(StringIO()):
                menu.practice_keys(sounds)
            self.assertEqual([call.args[0] for call in sounds.play.call_args_list],
                             ['SQUARE', 'L1'])
            self.assertEqual([call.args[0] for call in menu._entry_speech.say.call_args_list][1:],
                             ['Square.', 'Triangle.'])
            sounds.stop.assert_called_once()

    def test_console_arrow_codes_are_available_to_menus(self):
        with patch.object(accessible_menu.msvcrt, 'getwch',
                          side_effect=('\xe0', 'H', '\x00', 'P', '\xe0', 'K', '\x00', 'M')):
            self.assertEqual(accessible_menu.Menu.read_key(), 'up')
            self.assertEqual(accessible_menu.Menu.read_key(), 'down')
            self.assertEqual(accessible_menu.Menu.read_key(), 'left')
            self.assertEqual(accessible_menu.Menu.read_key(), 'right')

    def test_window_keys_bypass_console_and_close_exits(self):
        window = Mock()
        window.is_active.return_value = True
        window.read_key.side_effect = ['down', '__close__']
        with patch.dict(sys.modules, {'window_menu': window}), \
                patch.object(accessible_menu.msvcrt, 'getwch') as console:
            self.assertEqual(accessible_menu.Menu.read_key(), 'down')
            with self.assertRaises(EOFError):
                accessible_menu.Menu.read_key()
            console.assert_not_called()

    def test_default_cli_uses_window_and_explicit_console_flag_preserves_fallback(self):
        for arguments, expected in (([], True), (['--console-menu'], False),
                                    (['--developer-menu'], False)):
            with self.subTest(arguments=arguments), patch.object(accessible_menu, 'Menu') as menu:
                self.assertEqual(accessible_menu.main(arguments), 0)
                self.assertEqual(menu.call_args.kwargs['windowed'], expected)

    def test_window_navigation_uses_surface_without_console_page_output(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.windowed = True
            window = Mock()
            window.is_active.return_value = True
            window.read_key.side_effect = ['3', 'down', 'down', 'right', '0', '0']
            output = StringIO()
            with patch.dict(sys.modules, {'window_menu': window}), redirect_stdout(output):
                menu.run()
            self.assertEqual(output.getvalue(), '')
            self.assertTrue(menu.handoff_sound)
            self.assertEqual(window.show.call_count, 3)
            menu._entry_speech.say.assert_not_called()

    def test_window_practice_uses_native_selection_without_duplicate_prism(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.windowed = True
            sounds = Mock()
            sounds.play.return_value = {'result': True}
            window = Mock()
            window.is_active.return_value = True
            window.read_key.side_effect = ['q', 'e', 'k', '\r', '0']
            with patch.dict(sys.modules, {'window_menu': window}):
                menu.practice_keys(sounds)
            self.assertEqual([call.args[0] for call in sounds.play.call_args_list],
                             ['L1', 'R1', 'X', 'TRIANGLE'])
            menu._entry_speech.say.assert_not_called()

    def test_window_mouse_selection_routes_to_settings_and_back(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.windowed = True
            window = Mock()
            window.is_active.return_value = True
            window.read_key.side_effect = ['select:2', '\r', 'select:2', '\r',
                                           'select:6', '\r', 'select:3', '\r']
            with patch.dict(sys.modules, {'window_menu': window}):
                menu.run()
            self.assertTrue(menu.handoff_sound)
            menu._entry_speech.say.assert_not_called()

    def test_window_errors_use_native_dialog(self):
        window = Mock()
        with patch.dict(sys.modules, {'window_menu': window}):
            accessible_menu.WindowMessages().say('Preview unavailable.')
        window.message_box.assert_called_once_with('Preview unavailable.')

    def test_window_play_redirects_diagnostics_and_keeps_auto_start(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.windowed = True
            menu.diagnostics = True
            with patch.object(accessible_menu, 'LOGS', Path(folder)), \
                    patch.object(accessible_menu.subprocess, 'run') as run:
                run.return_value.returncode = 0
                menu.play_duckstation(from_title=True, audio_output='USB Headphones')
            self.assertIn('--auto-start', run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs['creationflags'], accessible_menu.subprocess.CREATE_NO_WINDOW)
            self.assertEqual(run.call_args.kwargs['stderr'], accessible_menu.subprocess.STDOUT)
            self.assertEqual(len(list((Path(folder) / 'launcher-runs').glob('*.log'))), 1)

    def test_invalid_volume_defaults_on_load_and_is_rejected_on_save(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for invalid in (-10, 210, True, 'loud'):
                values = launcher_settings.default_settings()
                values['cue_volume'] = invalid
                path.write_text(json.dumps(values))
                self.assertEqual(launcher_settings.load_settings(path)['cue_volume'], 100)
                with self.assertRaises(ValueError):
                    launcher_settings.save_settings(values, path)

    def test_practice_window_is_shown_before_audio_initialization_starts(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            cursor, sounds = Mock(), Mock()
            order = []
            cursor.show.side_effect = lambda *args: order.append('show')
            sounds.start.side_effect = lambda: order.append('audio start')
            with patch.object(menu, 'menu_surface', return_value=cursor), \
                    patch.object(menu, 'read_key', return_value='0'):
                menu.practice_keys(sounds)
            self.assertEqual(order, ['show', 'audio start'])

    def test_practice_launch_does_not_create_diagnostic_files(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.practice_keys = Mock()
            module = Mock()
            sounds = module.PracticeSounds.return_value
            before = sorted(str(p) for p in Path(folder).rglob('*'))
            with patch.dict(sys.modules, {'launcher_practice': module}), \
                    patch.object(accessible_menu, 'LOGS', Path(folder)):
                menu.audition()
            self.assertEqual(before, sorted(str(p) for p in Path(folder).rglob('*')))
            sounds.close.assert_called_once_with(wait=False)
            menu._close_practice_audio()
            sounds.close.assert_called_with()

    def test_handoff_is_last_sound_and_enter_plays_without_repeating_name(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            sounds = Mock()
            sounds.play.return_value = sounds.play_handoff.return_value = {'result': True}
            cursor = Mock()
            with patch.object(menu, 'menu_surface', return_value=cursor), \
                    patch.object(menu, 'read_key', side_effect=(
                        'down', 'down', 'down', 'down', 'down', 'down',
                        '\r', 'h', 'q', '\r', 'down', '\r')):
                menu.practice_keys(sounds)
            self.assertEqual(cursor.show.call_args.args[1][-2:],
                             [('', 'Handoff'), ('0', 'Return to main menu')])
            self.assertEqual(sounds.play_handoff.call_count, 2)
            sounds.play.assert_called_once_with('L1')
            self.assertEqual([c.args[0] for c in menu._entry_speech.say.call_args_list].count('Handoff.'), 1)

    def test_sound_practice_maps_each_key_to_one_cue(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            sounds = Mock()
            sounds.play.return_value = {"result": True}
            with patch.object(menu, "read_key", side_effect=("l", "k", "q", "e", "i", "j", "\x1b")):
                menu.practice_keys(sounds)

            self.assertEqual([call.args[0] for call in sounds.play.call_args_list],
                             ["CIRCLE", "X", "L1", "R1", "TRIANGLE", "SQUARE"])
            spoken = [call.args[0] for call in menu._entry_speech.say.call_args_list]
            self.assertEqual(len(spoken), 1)
            sounds.stop.assert_called_once_with()


    def test_diagnostics_default_off_and_toggle_persists(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            self.assertFalse(menu.diagnostics)
            with patch.object(menu, 'read_key', side_effect=('5', '0')), redirect_stdout(StringIO()):
                menu.settings_menu()
            self.assertTrue(launcher_settings.load_settings(menu.preferences_path)['diagnostics'])
            self.assertEqual(menu._setting_value('5'), 'On')

    def test_window_play_without_diagnostics_creates_no_session_log(self):
        with TemporaryDirectory() as folder:
            menu = self.make_menu(folder)
            menu.windowed = True
            with patch.object(accessible_menu, 'LOGS', Path(folder)), \
                    patch.object(accessible_menu.subprocess, 'run') as run:
                run.return_value.returncode = 0
                menu.play_duckstation(from_title=True, audio_output='USB Headphones')
            self.assertNotIn('--diagnostics', run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs['stdout'], accessible_menu.subprocess.DEVNULL)
            self.assertFalse((Path(folder) / 'launcher-runs').exists())


if __name__ == "__main__":
    unittest.main()
