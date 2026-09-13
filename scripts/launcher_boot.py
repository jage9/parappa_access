"""Windowed release entry point with visible startup errors."""
import ctypes
from pathlib import Path
import runpy
import sys


def main():
    menu = Path(__file__).with_name('accessible-menu.py')
    sys.argv[0] = str(menu)
    try:
        runpy.run_path(str(menu), run_name='__main__')
    except SystemExit as exit_status:
        if exit_status.code:
            ctypes.windll.user32.MessageBoxW(None,
                'Parappa Access could not start with those options. Run Parappa Access.exe without extra arguments.',
                'Parappa Access', 0x10)
        raise
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(
            None, 'Parappa Access could not start.\n\n' + str(error),
            'Parappa Access', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
