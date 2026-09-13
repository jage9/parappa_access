"""Keep a Windows console menu in place with a visual selection highlight."""
import ctypes
from ctypes import wintypes
import sys
import textwrap


class Coord(ctypes.Structure):
    _fields_ = [('x', ctypes.c_short), ('y', ctypes.c_short)]


class Rect(ctypes.Structure):
    _fields_ = [(name, ctypes.c_short) for name in ('left', 'top', 'right', 'bottom')]


class BufferInfo(ctypes.Structure):
    _fields_ = [('size', Coord), ('cursor', Coord), ('attributes', wintypes.WORD),
                ('window', Rect), ('maximum_size', Coord)]


class CursorInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('visible', wintypes.BOOL)]


class Character(ctypes.Union):
    _fields_ = [('unicode', wintypes.WCHAR), ('ascii', ctypes.c_char)]


class Cell(ctypes.Structure):
    _fields_ = [('character', Character), ('attributes', wintypes.WORD)]


class ConsoleMenuCursor:
    def __init__(self):
        self.end = None
        self.first_row = None
        self.selected = None
        self.caret_column = 3
        self.width = 0
        self.api = None
        self.saved_cursor = None
        if sys.stdout.isatty():
            self.api = ctypes.WinDLL('kernel32', use_last_error=True)
            self.api.GetStdHandle.argtypes = [wintypes.DWORD]
            self.api.GetStdHandle.restype = wintypes.HANDLE
            self.api.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(BufferInfo)]
            self.api.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
            self.api.SetConsoleCursorPosition.argtypes = [wintypes.HANDLE, Coord]
            self.api.SetConsoleCursorPosition.restype = wintypes.BOOL
            self.api.GetConsoleCursorInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(CursorInfo)]
            self.api.GetConsoleCursorInfo.restype = wintypes.BOOL
            self.api.SetConsoleCursorInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(CursorInfo)]
            self.api.SetConsoleCursorInfo.restype = wintypes.BOOL
            self.api.FillConsoleOutputAttribute.argtypes = [wintypes.HANDLE, wintypes.WORD,
                wintypes.DWORD, Coord, ctypes.POINTER(wintypes.DWORD)]
            self.api.FillConsoleOutputAttribute.restype = wintypes.BOOL
            self.api.FillConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.WCHAR,
                wintypes.DWORD, Coord, ctypes.POINTER(wintypes.DWORD)]
            self.api.FillConsoleOutputCharacterW.restype = wintypes.BOOL
            self.api.SetConsoleTextAttribute.argtypes = [wintypes.HANDLE, wintypes.WORD]
            self.api.SetConsoleTextAttribute.restype = wintypes.BOOL
            self.api.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]
            self.api.SetConsoleTitleW.restype = wintypes.BOOL
            self.api.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            self.api.GetConsoleMode.restype = wintypes.BOOL
            self.api.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.api.SetConsoleMode.restype = wintypes.BOOL
            self.api.WriteConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR,
                wintypes.DWORD, Coord, ctypes.POINTER(wintypes.DWORD)]
            self.api.WriteConsoleOutputCharacterW.restype = wintypes.BOOL
            self.api.WriteConsoleOutputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Cell),
                Coord, Coord, ctypes.POINTER(Rect)]
            self.api.WriteConsoleOutputW.restype = wintypes.BOOL
            self.handle = self.api.GetStdHandle(-11)

    def show(self, title, items, selected, instructions):
        self.finish()
        self.title, self.instructions = title, instructions
        original = None
        info = BufferInfo()
        self.width = 80
        if self.api and self.api.GetConsoleScreenBufferInfo(self.handle, ctypes.byref(info)):
            saved = CursorInfo()
            if self.api.GetConsoleCursorInfo(self.handle, ctypes.byref(saved)):
                self.saved_cursor = saved
                self.api.SetConsoleCursorInfo(self.handle, ctypes.byref(CursorInfo(saved.size, False)))
            self.api.SetConsoleTitleW('Parappa Access')
            original = info.attributes
            self.width = info.size.x
            mode = wintypes.DWORD()
            if (self.api.GetConsoleMode(self.handle, ctypes.byref(mode)) and
                    self.api.SetConsoleMode(self.handle, mode.value | 4)):
                # Windows Terminal needs VT erase for its display and history;
                # filling the legacy viewport alone leaves old menu text.
                try:
                    sys.stdout.write('\x1b[2J\x1b[3J\x1b[H')
                    sys.stdout.flush()
                finally:
                    self.api.SetConsoleMode(self.handle, mode.value)
            else:
                origin = Coord(0, 0)
                count = info.size.x * info.size.y
                written = wintypes.DWORD()
                self.api.FillConsoleOutputCharacterW(self.handle, ' ', count, origin, ctypes.byref(written))
                self.api.FillConsoleOutputAttribute(self.handle, 0x0F, count, origin, ctypes.byref(written))
                self.api.SetConsoleCursorPosition(self.handle, origin)
            self.api.SetConsoleTextAttribute(self.handle, 0x0F)
        width = max(1, self.width - 1)
        self.lines = [textwrap.wrap((f'{key}. {label}' if key else label), width) for key, label in items]
        footer = [''] + textwrap.wrap(instructions, width)
        self.offsets = []
        row = 0
        for lines in self.lines:
            self.offsets.append(row)
            row += len(lines)
        page = [title] + [line for lines in self.lines for line in lines] + footer
        rendered = False
        if self.api and self.api.GetConsoleScreenBufferInfo(self.handle, ctypes.byref(info)):
            origin = info.cursor.y
            if origin + len(page) < info.size.y:
                cells = (Cell * (self.width * len(page)))()
                for y, line in enumerate(page):
                    for x, char in enumerate(line[:self.width].ljust(self.width)):
                        cell = cells[y * self.width + x]
                        cell.character.unicode = char
                        cell.attributes = 0x0F
                region = Rect(0, origin, self.width - 1, origin + len(page) - 1)
                rendered = bool(self.api.WriteConsoleOutputW(self.handle, cells,
                    Coord(self.width, len(page)), Coord(0, 0), ctypes.byref(region)))
                if rendered:
                    # Paint in one operation without output scrolling/cursor
                    # advancement that NVDA can interpret as new console text.
                    self.end = Coord(0, origin + len(page))
                    self.first_row = origin + 1
        if not rendered:
            print('\n'.join(page), flush=True)
        if original is not None:
            self.api.SetConsoleTextAttribute(self.handle, original)
        info = BufferInfo()
        if rendered:
            self.move(selected)
        elif self.api and self.api.GetConsoleScreenBufferInfo(self.handle, ctypes.byref(info)):
            first = info.cursor.y - row - len(footer)
            if first >= 0:
                self.end = Coord(info.cursor.x, info.cursor.y)
                self.first_row = first
                self.move(selected)

    def update(self, items, selected, advance_caret=False):
        """Replace changed setting text in place; do not append navigation output."""
        if self.first_row is None:
            return
        # A newly selected device can have a longer name and wrap differently.
        # Reflow the visual page without repeating its Prism entry announcement.
        if any(len(textwrap.wrap((f'{key}. {label}' if key else label), max(1, self.width - 1))) != len(self.lines[index])
               for index, (key, label) in enumerate(items)):
            self.show(self.title, items, selected, self.instructions)
            if advance_caret:
                self.move(selected, advance_caret=True)
            return
        written = wintypes.DWORD()
        for index, (key, label) in enumerate(items):
            lines = textwrap.wrap((f'{key}. {label}' if key else label), max(1, self.width - 1))
            if lines != self.lines[index] and len(lines) == len(self.lines[index]):
                for offset, line in enumerate(lines):
                    text = line.ljust(self.width)
                    self.api.WriteConsoleOutputCharacterW(self.handle, text, len(text),
                        Coord(0, self.first_row + self.offsets[index] + offset), ctypes.byref(written))
                self.lines[index] = lines
        self.move(selected, advance_caret=advance_caret)

    def _highlight(self, selected, attributes):
        if selected is not None:
            written = wintypes.DWORD()
            self.api.FillConsoleOutputAttribute(self.handle, attributes, self.width * len(self.lines[selected]),
                Coord(0, self.first_row + self.offsets[selected]), ctypes.byref(written))

    def move(self, selected, advance_caret=False):
        if self.first_row is not None:
            self._highlight(self.selected, 0x0F)
            self._highlight(selected, 0xF0)
            # Move within the label on horizontal changes, so NVDA detects a
            # caret change without waiting on an unchanged shortcut digit.
            if advance_caret and self.selected == selected:
                self.caret_column = 4 if self.caret_column == 3 else 3
            else:
                self.caret_column = 3
            self.selected = selected
            # NVDA's console arrow handler waits for caret movement before
            # reading the current line. Keep its hidden caret on the selected
            # item, otherwise it waits and reads the parked page heading.
            self.api.SetConsoleCursorPosition(self.handle,
                Coord(min(self.caret_column, self.width - 1), self.first_row + self.offsets[selected]))

    def finish(self):
        if self.end is not None:
            self._highlight(self.selected, 0x0F)
            self.api.SetConsoleCursorPosition(self.handle, self.end)
        self.end = self.first_row = None
        self.selected = None
        if self.saved_cursor is not None:
            self.api.SetConsoleCursorInfo(self.handle, ctypes.byref(self.saved_cursor))
            self.saved_cursor = None
