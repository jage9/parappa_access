"""Recognize local disc files DuckStation can open."""
from pathlib import Path


SUPPORTED_DISC_EXTENSIONS = (
    ".ccd", ".cue", ".bin", ".img", ".iso", ".ecm", ".chd", ".mds", ".pbp", ".m3u",
)
EXPERIMENTAL_DISC_EXTENSIONS = frozenset(SUPPORTED_DISC_EXTENSIONS[2:])


class DiscFileError(ValueError):
    """A selected file is not a readable supported DuckStation disc file."""


def resolve_disc_files(descriptor: str | Path) -> tuple[Path, ...]:
    """Validate one selected disc file; DuckStation resolves its layout and companions."""
    descriptor = Path(descriptor)
    if descriptor.suffix.lower() not in SUPPORTED_DISC_EXTENSIONS:
        raise DiscFileError("Select a supported PlayStation disc file or playlist.")
    if not descriptor.is_file():
        raise FileNotFoundError("The selected disc file does not exist: " + str(descriptor))
    try:
        with descriptor.open("rb") as stream:
            stream.read(1)
    except OSError as error:
        raise DiscFileError("The selected disc file cannot be read: " + str(descriptor)) from error
    return (descriptor,)
