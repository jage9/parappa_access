"""One-time, non-overwriting import of raw Redux PS1 memory cards."""
import hashlib
import json
from pathlib import Path


def configure_test_cards(settings, nonpersistent=False):
    if type(nonpersistent) is not bool:
        raise TypeError('nonpersistent must be a bool.')
    if not settings.has_section('MemoryCards'):
        settings.add_section('MemoryCards')
    for slot in (1, 2):
        card_type = 'NonPersistent' if nonpersistent and slot == 1 else 'None'
        settings.set('MemoryCards', f'Card{slot}Type', card_type)
        settings.remove_option('MemoryCards', f'Card{slot}Path')


def import_redux_cards(root):
    root = Path(root)
    source_dir = root / 'tools' / 'pcsx-redux'
    config = json.loads((source_dir / 'pcsx.json').read_text(encoding='utf-8'))['emulator']
    destination = root / 'tools' / 'research' / 'duckstation-stock' / 'portable' / 'memcards'
    cards = {}
    for slot in (1, 2):
        target = destination / f'redux-import-slot{slot}.mcd'
        if target.exists():
            data = target.read_bytes()
        elif config.get(f'Mcd{slot}Inserted', True):
            source = Path(config[f'Mcd{slot}'])
            if not source.is_absolute():
                source = source_dir / source
            data = source.read_bytes()
        else:
            continue
        if len(data) != 131072 or data[:2] != b'MC':
            raise ValueError(f'Slot {slot} is not a raw 128 KiB PS1 memory card.')
        if not target.exists():
            destination.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
            print(f'Imported memory card {slot}: {target}', flush=True)
        print(f'DuckStation card {slot}: {target}; SHA256 {hashlib.sha256(data).hexdigest()}', flush=True)
        cards[slot] = target.resolve()
    return cards
