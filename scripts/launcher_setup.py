"""Read-only readiness checks for the current local installation."""
from pathlib import Path
import configparser


def check_setup(root):
    root = Path(root)
    portable = root / 'tools/research/duckstation-stock/portable'
    required = [portable / 'duckstation-qt-x64-ReleaseLTCG.exe', portable / 'settings.ini']
    disc = root / 'game/Parappa the Rapper [U] [SCUS-94183]'
    required += [disc.with_suffix(suffix) for suffix in ('.ccd', '.img', '.sub')]
    required += [root / 'sounds' / (button + '.wav') for button in ('circle', 'x', 'square', 'triangle', 'l1', 'r1')]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        return ['Missing ' + name + '.' for name in missing]
    settings = configparser.ConfigParser(interpolation=None)
    try:
        settings.read(portable / 'settings.ini')
        bios_dir = Path(settings.get('BIOS', 'SearchDirectory', fallback='bios'))
        if not bios_dir.is_absolute():
            bios_dir = portable / bios_dir
        bios_name = settings.get('BIOS', 'PathNTSCU', fallback='')
        if not bios_name or not (bios_dir / bios_name).is_file():
            return ['The configured US BIOS is missing.']
    except (OSError, configparser.Error) as error:
        return ['Cannot read emulator settings: ' + str(error)]
    return []
