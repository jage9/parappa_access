"""Stock DuckStation keyboard mapping, pinned to 3b30876e9.

src/util/input_manager.cpp, GetKeyboardGenericBindingMapping.
PaRappa uses the digital controller; analogue-stick keys are left unused.
"""
PAD_KEYS = {
    'Up':'UpArrow', 'Right':'RightArrow', 'Down':'DownArrow', 'Left':'LeftArrow',
    'Triangle':'I', 'Circle':'L', 'Cross':'K', 'Square':'J',
    'L1':'Q', 'L2':'1', 'R1':'E', 'R2':'3',
    'Start':'Enter', 'Select':'Backspace',
}
# Derive practice keys from the same bindings applied to DuckStation.
# Spaces make the shoulder-button names unambiguous to console screen readers.
LEARN_BUTTONS = {'Triangle':('Triangle','TRIANGLE'), 'Square':('Square','SQUARE'),
                 'Cross':('X','X'), 'Circle':('Circle','CIRCLE'),
                 'L1':('L 1','L1'), 'R1':('R 1','R1')}
LEARN_KEYS = {PAD_KEYS[button].lower():item for button,item in LEARN_BUTTONS.items()}
SCORE_VK=0x5a
RATING_VK=0x58
LYRICS_VK=0x59  # Y toggles spoken rap lyrics; off by default.
HINT_VK=0xbf  # Slash or Shift+Slash (question mark) on the current keyboard.


def apply_stock_keyboard(settings):
    if not settings.has_section('Pad1'):settings.add_section('Pad1')
    for button,key in PAD_KEYS.items():
        settings.set('Pad1',button,'Keyboard/'+key)
