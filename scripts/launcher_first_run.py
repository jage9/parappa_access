"""First-run preparation using native dialogs and user-owned files."""
import configparser
import ctypes
import json
import threading
from pathlib import Path
from native_file_dialog import choose_file
from duckstation_paths import duckstation_directory, EXECUTABLE_NAME
from disc_files import (DiscFileError, EXPERIMENTAL_DISC_EXTENSIONS,
                        SUPPORTED_DISC_EXTENSIONS, resolve_disc_files)
from launcher_setup import configured_bios_path, game_image


def download_with_status(root):
    import window_menu
    from duckstation_download import download_duckstation
    cancelled = threading.Event()
    outcome = {}
    window_menu.show('Download DuckStation', [('0', 'Cancel download')], 0,
                     'Downloading the official emulator. Escape cancels.')
    def work():
        try:
            outcome['path'] = download_duckstation(root, cancelled=cancelled)
        except Exception as error:
            outcome['error'] = error
        finally:
            if not cancelled.is_set():
                window_menu.call_soon(lambda: window_menu.window_menu._events.append('__download_done__'))
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    try:
        while True:
            key = window_menu.read_key()
            if key == '__download_done__':
                if 'error' in outcome:
                    raise outcome['error']
                return outcome['path']
            if key in ('0', '\x1b', '\r', '__close__'):
                cancelled.set()
                return None
    finally:
        window_menu.finish()


def _validate_disc(disc):
    disc = Path(disc)
    try:
        resolve_disc_files(disc)
    except FileNotFoundError as error:
        raise ValueError('Select an existing PlayStation disc file or playlist.') from error
    except DiscFileError as error:
        raise ValueError(str(error)) from error
    return disc


def _show_experimental_disc_notice():
    ctypes.windll.user32.MessageBoxW(
        None,
        'This disc format has not been tested with Parappa Access. '
        'DuckStation will check the game version when you choose Play.',
        'Untested disc format', 0x40)


def _stored_disc(root):
    try:
        disc = Path(game_image(root))
        if not disc.is_absolute():
            disc = root / disc
        return _validate_disc(disc)
    except (OSError, AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _read_settings(settings_path):
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    if settings_path.exists():
        with settings_path.open('r', encoding='utf-8') as stream:
            config.read_file(stream)
    return config


def _write_default_settings(config, bios):
    config.read_dict({
        'Main': {'SetupWizardIncomplete': 'false', 'EmulationSpeed': '1.0',
                 'SyncToHostRefreshRate': 'false', 'RewindEnable': 'false',
                 'RunaheadFrameCount': '0', 'SaveStateOnExit': 'false',
                 'DisableAllEnhancements': 'true'},
        'BIOS': {'SearchDirectory': str(bios.parent.resolve()), 'PathNTSCU': bios.name,
                 'PatchFastBoot': 'false'},
        'GPU': {'Renderer': 'Automatic', 'ResolutionScale': '1'},
        'Display': {'VSync': 'false'},
        'Audio': {'Backend': 'Cubeb', 'StretchMode': 'None', 'OutputLatencyMinimal': 'true', 'BufferMS': '30'},
        'Pad1': {'Type': 'DigitalController'},
        'Logging': {'LogToFile': 'false'},
    })


def _record_disc(root, disc):
    profile = root / 'logs/install-settings.json'
    profile.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if profile.is_file():
        try:
            existing = json.loads(profile.read_text(encoding='utf-8'))
            if isinstance(existing, dict):
                data.update(existing)
        except (OSError, json.JSONDecodeError):
            pass
    resolved = str(disc.resolve())
    if data.get('game_image') != resolved:
        data['game_image'] = resolved
        profile.write_text(json.dumps(data, indent=2), encoding='utf-8')


def prepare(root):
    root = Path(root)
    portable = duckstation_directory(root)
    if not (portable / EXECUTABLE_NAME).is_file():
        answer = ctypes.windll.user32.MessageBoxW(None,
            'Parappa Access needs DuckStation. Download the tested official release?\n\n'
            'DuckStation is by stenzek and contributors: https://www.duckstation.org/\n'
            'It is licensed separately under CC BY-NC-ND 4.0. No game or BIOS is included.',
            'Set up Parappa Access', 0x24)
        if answer != 6:
            return False
        portable = download_with_status(root)
        if portable is None:
            return False

    disc = _stored_disc(root)
    if disc is None:
        file_filter = ';'.join('*' + suffix for suffix in SUPPORTED_DISC_EXTENSIONS)
        selected = choose_file('Select your PaRappa disc image or playlist',
                               'DuckStation disc image', file_filter)
        if not selected:
            return False
        disc = _validate_disc(selected)
        if disc.suffix.lower() in EXPERIMENTAL_DISC_EXTENSIONS:
            _show_experimental_disc_notice()

    settings_path = portable / 'settings.ini'
    settings_existed = settings_path.exists()
    config = _read_settings(settings_path)
    bios_path = configured_bios_path(portable, config)
    if bios_path is None or not bios_path.is_file():
        selected_bios = choose_file('Select your PlayStation BIOS', 'BIOS image', '*.bin;*.rom')
        if not selected_bios:
            return False
        bios = Path(selected_bios)
        if not bios.is_file():
            raise ValueError('Select an existing PlayStation BIOS image.')
        if not settings_existed:
            _write_default_settings(config, bios)
        else:
            if not config.has_section('BIOS'):
                config.add_section('BIOS')
            config.set('BIOS', 'SearchDirectory', str(bios.parent.resolve()))
            config.set('BIOS', 'PathNTSCU', bios.name)
            if not config.has_option('BIOS', 'PatchFastBoot'):
                config.set('BIOS', 'PatchFastBoot', 'false')
        with settings_path.open('x' if not settings_existed else 'w', encoding='utf-8') as stream:
            config.write(stream)
    marker = portable / 'portable.txt'
    if not marker.exists():
        with marker.open('x'):
            pass
    _record_disc(root, disc)
    return True
