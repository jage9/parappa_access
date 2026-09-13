"""Persistent player cards and isolated DuckStation testing modes."""
from pathlib import Path
from duckstation_paths import duckstation_directory


def configure_test_cards(settings, nonpersistent=False):
    if type(nonpersistent) is not bool:
        raise TypeError('nonpersistent must be a bool.')
    if not settings.has_section('MemoryCards'):
        settings.add_section('MemoryCards')
    for slot in (1, 2):
        card_type = 'NonPersistent' if nonpersistent and slot == 1 else 'None'
        settings.set('MemoryCards', f'Card{slot}Type', card_type)
        settings.remove_option('MemoryCards', f'Card{slot}Path')


def configure_player_cards(root, settings):
    """Select persistent cards without reading another emulator or writing cards."""
    folder = duckstation_directory(root)
    if not settings.has_section('MemoryCards'):
        settings.add_section('MemoryCards')
    for slot in (1, 2):
        kind = settings.get('MemoryCards', f'Card{slot}Type', fallback='None')
        if kind not in ('None', 'NonPersistent'):
            continue  # Preserve an explicitly configured persistent card mode.
        existing = folder / 'memcards' / f'redux-import-slot{slot}.mcd'
        target = existing if existing.is_file() else folder / 'memcards' / f'shared_card_{slot}.mcd'
        settings.set('MemoryCards', f'Card{slot}Type', 'Shared')
        settings.set('MemoryCards', f'Card{slot}Path', str(target.resolve()))
