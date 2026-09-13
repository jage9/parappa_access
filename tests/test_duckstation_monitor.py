import _bootstrap
import unittest
from duckstation_monitor import STATE,completed_scene_reset,read_monitor_sample


class SceneResetTests(unittest.TestCase):
    def test_stage3_entry_does_not_announce_a_final_score(self):
        self.assertFalse(completed_scene_reset(False, 4134, 0, False))

    def test_preroll_and_retry_are_not_completed_rounds(self):
        self.assertFalse(completed_scene_reset(True, 0xFFFFFF70, 0, False))
        self.assertFalse(completed_scene_reset(True, 26153, 0, True))

    def test_observed_round_end_can_announce(self):
        self.assertTrue(completed_scene_reset(True, 26153, 0, False))


class DiagnosticReadTests(unittest.TestCase):
    class FakeRAM:
        def __init__(self):
            self.reads=[]

        def read(self,address,size):
            self.reads.append((address,size))
            return bytes(size)

    def test_off_mode_keeps_required_gameplay_state_but_skips_log_snapshots(self):
        ram=self.FakeRAM()
        a,common,result,roots,b=read_monitor_sample(ram,False)
        self.assertEqual(len(a),0xb0)
        self.assertEqual(len(b),0xb0)
        self.assertEqual(len(common),0x148)  # Still contains score at offset 0x146.
        self.assertEqual(len(result[0]),4)   # Retry/dialog latch remains monitored.
        self.assertEqual(result[1],b'')
        self.assertEqual(ram.reads,[(STATE,0xb0),(0x800916d0,0x148),(0x8006ed74,4),
                                    (0x800943d0,8),(STATE,0xb0)])

    def test_diagnostics_mode_retains_full_event_snapshots(self):
        ram=self.FakeRAM()
        _,common,result,_,_=read_monitor_sample(ram,True)
        self.assertEqual(len(common),0x170)
        self.assertEqual(len(result[1]),64)
        self.assertIn((0x80092f10,64),ram.reads)
