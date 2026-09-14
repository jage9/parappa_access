"""Check the loaded game executable before starting accessibility observation.

The fingerprint is the PS-X EXE load payload from our verified SCUS-94183
disc. DuckStation performs container decoding; no ROM bytes are distributed.
This identifies executable compatibility, not the integrity of every asset.
"""
import hashlib

ENTRY_POINT = 0x80028590
LOAD_ADDRESS = 0x80010000
LOAD_SIZE = 0x5F000
PAYLOAD_SHA256 = '2979aba44a796e579bc289c13b97758086663e12fdf729996aef514866ce6ed6'


class GameIdentityError(ValueError):
    """The loaded game cannot be identified as our supported executable."""


def verify_loaded_game(read):
    payload = read(LOAD_ADDRESS, LOAD_SIZE)
    if len(payload) != LOAD_SIZE or hashlib.sha256(payload).hexdigest() != PAYLOAD_SHA256:
        raise GameIdentityError('This game does not match the supported US PaRappa version '
                         '(SCUS-94183). Accessibility playback was not started.')
    return PAYLOAD_SHA256
