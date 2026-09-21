import _bootstrap
import configparser
import unittest
from duckstation_keyboard import apply_stock_keyboard,LEARN_KEYS,LEARN_BUTTONS,SCORE_VK,RATING_VK,HINT_VK,LYRICS_VK,SUBTITLES_VK
from duckstation_developer import LANES


class KeyboardTests(unittest.TestCase):
    def test_migration_preserves_other_settings_and_aligns_learn_and_driver(self):
        settings=configparser.ConfigParser();settings.optionxform=str
        settings.read_dict({'Pad1':{'Type':'DigitalController','Cross':'Keyboard/X'},
                            'Audio':{'Backend':'Cubeb'}})
        apply_stock_keyboard(settings)
        self.assertEqual(settings['Pad1']['Type'],'DigitalController')
        self.assertEqual(settings['Audio']['Backend'],'Cubeb')
        for key,item in LEARN_KEYS.items():
            button=next(button for button,labels in LEARN_BUTTONS.items() if labels==item)
            self.assertEqual(settings['Pad1'][button],'Keyboard/'+key.upper())
        self.assertEqual({v[1] for v in LANES.values()},
                         {ord(k.upper()) for k in LEARN_KEYS})
        controller_vks={ord(v.removeprefix('Keyboard/')) for v in settings['Pad1'].values()
                        if v.startswith('Keyboard/') and len(v.removeprefix('Keyboard/'))==1}
        self.assertTrue(controller_vks.isdisjoint((SCORE_VK,RATING_VK,HINT_VK,LYRICS_VK,SUBTITLES_VK)))
