"""Temporarily add SDL standard-gamepad bindings to DuckStation's Pad1 INI.

DuckStation stores a string-list binding as repeated INI keys. This module
operates on the raw serialized INI text so it does not collapse those keys as
``configparser`` would.
"""
from __future__ import annotations

import re


PAD_SECTION = "Pad1"
INPUT_SOURCES_SECTION = "InputSources"

# DuckStation's SDL input source parses these SDL logical Gamepad names.
# The names correspond to the standardized gamepad layout, not raw button
# indices; see docs/controller-setup.md for the pinned-source evidence.
STANDARD_GAMEPAD_BINDINGS = (
    ("Up", "DPadUp"),
    ("Down", "DPadDown"),
    ("Left", "DPadLeft"),
    ("Right", "DPadRight"),
    ("Triangle", "Y"),
    ("Circle", "B"),
    ("Cross", "A"),
    ("Square", "X"),
    ("Select", "Back"),
    ("Start", "Start"),
    ("L1", "LeftShoulder"),
    ("R1", "RightShoulder"),
)

_SECTION_HEADER = re.compile(r"^\s*\[([^\]]*)\]")


def _line_parts(line: str) -> tuple[str, str]:
    """Return a line's content and its original line ending."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\n", "\r")):
        return line[:-1], line[-1:]
    return line, ""


def _section_blocks(lines: list[str], name: str) -> list[tuple[int, int]]:
    """Return all matching section ranges as ``(header, end)`` indices."""
    blocks: list[tuple[int, int]] = []
    current_name: str | None = None
    current_header: int | None = None
    for index, line in enumerate(lines):
        content, _ = _line_parts(line)
        match = _SECTION_HEADER.match(content.strip())
        if not match:
            continue
        if current_name == name and current_header is not None:
            blocks.append((current_header, index))
        current_name = match.group(1).strip()
        current_header = index
    if current_name == name and current_header is not None:
        blocks.append((current_header, len(lines)))
    return blocks


def _key_values(lines: list[str], section: str, key: str) -> list[tuple[int, str]]:
    values: list[tuple[int, str]] = []
    current_section: str | None = None
    for index, line in enumerate(lines):
        content, _ = _line_parts(line)
        stripped = content.strip()
        match = _SECTION_HEADER.match(stripped)
        if match:
            current_section = match.group(1).strip()
            continue
        if current_section != section or not stripped or stripped.startswith(("#", ";")):
            continue
        equal = content.find("=")
        if equal < 0 or content[:equal].strip() != key:
            continue
        raw_value = content[equal + 1:].strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] == '"':
            value = raw_value[1:-1]
        else:
            comment = min((position for marker in "#;" if (position := raw_value.find(marker)) >= 0), default=-1)
            value = raw_value if comment < 0 else raw_value[:comment]
            value = value.strip()
        values.append((index, value))
    return values


def _insert_in_section(lines: list[str], section: str, entries: list[str], newline: str) -> None:
    blocks = _section_blocks(lines, section)
    if not blocks:
        if lines:
            content, ending = _line_parts(lines[-1])
            if content:
                if ending:
                    lines.append(newline)
                else:
                    lines[-1] = lines[-1] + newline
            elif not ending:
                lines[-1] = lines[-1] + newline
        lines.append(f"[{section}]{newline}")
        lines.extend(f"{entry}{newline}" for entry in entries)
        return

    header, end = blocks[-1]
    insertion = end
    while insertion > header + 1:
        content, _ = _line_parts(lines[insertion - 1])
        if content.strip():
            break
        insertion -= 1
    if insertion > 0:
        prior_content, prior_ending = _line_parts(lines[insertion - 1])
        if prior_content and not prior_ending:
            lines[insertion - 1] += newline
    lines[insertion:insertion] = [f"{entry}{newline}" for entry in entries]


def _replace_scalar_value(line: str, value: str) -> str:
    content, ending = _line_parts(line)
    equal = content.find("=")
    if equal < 0:
        return line
    raw_value = content[equal + 1:]
    comment = min((position for marker in "#;" if (position := raw_value.find(marker)) >= 0), default=-1)
    value_text = raw_value if comment < 0 else raw_value[:comment]
    comment_text = "" if comment < 0 else raw_value[comment:]
    leading = value_text[:len(value_text) - len(value_text.lstrip(" \t"))]
    trailing = value_text[len(value_text.rstrip(" \t")):]
    if not leading and not trailing:
        leading = " "
    return content[:equal + 1] + leading + value + trailing + comment_text + ending


def _enable_sdl(lines: list[str], newline: str) -> None:
    values = _key_values(lines, INPUT_SOURCES_SECTION, "SDL")
    if values:
        for index, value in values:
            if value.lower() != "true":
                lines[index] = _replace_scalar_value(lines[index], "true")
        return
    _insert_in_section(lines, INPUT_SOURCES_SECTION, ["SDL = true"], newline)


def add_automatic_controller_bindings(text: str, player_id: int = 0) -> str:
    """Add SDL's standard gamepad aliases beside Pad1's existing bindings.

    ``player_id`` is DuckStation's SDL player ID (the number in ``SDL-0``),
    not an SDL joystick instance ID. The default is the first player slot.
    The function returns new INI text and does not touch a settings file.
    """
    if not isinstance(text, str):
        raise TypeError("settings text must be a string")
    if type(player_id) is not int:
        raise TypeError("player_id must be an integer")
    if player_id < 0:
        raise ValueError("player_id must be non-negative")

    lines = text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"
    if not _section_blocks(lines, PAD_SECTION):
        raise ValueError(f"settings text must contain [{PAD_SECTION}]")

    _enable_sdl(lines, newline)

    additions: list[str] = []
    for key, button in STANDARD_GAMEPAD_BINDINGS:
        binding = f"SDL-{player_id}/{button}"
        if binding not in {value for _, value in _key_values(lines, PAD_SECTION, key)}:
            additions.append(f"{key} = {binding}")
    _insert_in_section(lines, PAD_SECTION, additions, newline)
    return "".join(lines)


__all__ = ["STANDARD_GAMEPAD_BINDINGS", "add_automatic_controller_bindings"]
