"""Read-only readiness checks for the current local installation."""
from pathlib import Path
import configparser
import json
from duckstation_paths import EXECUTABLE_NAME, SETTINGS_NAME, duckstation_directory
from disc_files import DiscFileError, resolve_disc_files


def game_image(root):
    root = Path(root)
    profile = root / 'logs/install-settings.json'
    if profile.is_file():
        value = json.loads(profile.read_text(encoding='utf-8')).get('game_image')
        if value:
            return Path(value)
    return root / 'game/Parappa the Rapper [U] [SCUS-94183].ccd'


def configured_bios_path(portable, settings):
    """Return the configured NTSC-U BIOS path, or None when it is unset."""
    bios_name = settings.get('BIOS', 'PathNTSCU', fallback='').strip()
    if not bios_name:
        return None
    bios_name = Path(bios_name)
    if bios_name.is_absolute():
        return bios_name
    bios_dir = Path(settings.get('BIOS', 'SearchDirectory', fallback='bios'))
    if not bios_dir.is_absolute():
        bios_dir = Path(portable) / bios_dir
    return bios_dir / bios_name


def check_setup(root):
    root = Path(root)
    portable = duckstation_directory(root)
    required = [portable / EXECUTABLE_NAME, portable / SETTINGS_NAME]
    disc = Path(game_image(root))
    try:
        disc_files = resolve_disc_files(disc)
    except FileNotFoundError:
        required.append(disc)
    except DiscFileError as error:
        return ['Cannot use the selected game disc file: ' + str(error)]
    else:
        required.extend(disc_files)
    required += [root / 'sounds' / (button + '.wav') for button in ('circle', 'x', 'square', 'triangle', 'l1', 'r1')]
    missing = [str(path.relative_to(root) if path.is_relative_to(root) else path)
               for path in required if not path.is_file()]
    if missing:
        return ['Missing ' + name + '.' for name in missing]
    settings = configparser.ConfigParser(interpolation=None)
    try:
        settings.read(portable / 'settings.ini', encoding='utf-8')
        bios_path = configured_bios_path(portable, settings)
        if bios_path is None or not bios_path.is_file():
            return ['The configured US BIOS is missing.']
    except (OSError, UnicodeError, configparser.Error) as error:
        return ['Cannot read emulator settings: ' + str(error)]
    return []
