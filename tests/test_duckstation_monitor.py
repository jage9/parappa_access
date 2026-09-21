import _bootstrap
import unittest
import struct
from duckstation_monitor import STATE,CUE_POLL_GAP_NS,completed_scene_reset,cue_suppression_reason,read_monitor_sample
from duckstation_monitor import PROGRESS_BYTES,ALL_COOL_WORD,STAGE_SELECT_STATE,apply_all_cool


class FakeWritableRAM:
    def __init__(self):self.memory=bytearray(0x200000);self.writes=[]
    def read(self,address,size):return bytes(self.memory[address-0x80000000:address-0x80000000+size])
    def write(self,address,data):
        self.memory[address-0x80000000:address-0x80000000+len(data)]=data;self.writes.append(address)


class AllCoolCheatTests(unittest.TestCase):
    def test_new_game_progress_is_replaced_and_then_left_alone(self):
        ram=FakeWritableRAM()
        ram.write(PROGRESS_BYTES,bytes([1,0,0,0,0,0]));ram.writes.clear()
        self.assertEqual(apply_all_cool(ram,stage_select=False),['save_struct'])
        self.assertEqual(ram.read(PROGRESS_BYTES,6),b'\x03'*6)
        self.assertEqual(ram.read(ALL_COOL_WORD,4),b'\x01\x00\x00\x00')
        self.assertEqual(apply_all_cool(ram,stage_select=False),[])
        self.assertEqual(sorted(set(ram.writes)),[PROGRESS_BYTES,ALL_COOL_WORD])

    def test_stage_select_copy_is_patched_only_while_showing(self):
        ram=FakeWritableRAM()
        ram.write(PROGRESS_BYTES,b'\x03'*6);ram.write(ALL_COOL_WORD,b'\x01\x00\x00\x00')
        ram.write(STAGE_SELECT_STATE+0x0e,struct.pack('<7H',1,0,0,0,0,0,0));ram.writes.clear()
        self.assertEqual(apply_all_cool(ram,stage_select=False),[])
        self.assertEqual(apply_all_cool(ram,stage_select=True),['stage_select'])
        self.assertEqual(struct.unpack('<7H',ram.read(STAGE_SELECT_STATE+0x0e,14)),(3,3,3,3,3,3,1))
        self.assertEqual(apply_all_cool(ram,stage_select=True),[])


class SceneResetTests(unittest.TestCase):
    def test_stage3_entry_does_not_announce_a_final_score(self):
        self.assertFalse(completed_scene_reset(False, 4134, 0, False))

    def test_preroll_and_retry_are_not_completed_rounds(self):
        self.assertFalse(completed_scene_reset(True, 0xFFFFFF70, 0, False))
        self.assertFalse(completed_scene_reset(True, 26153, 0, True))

    def test_observed_round_end_can_announce(self):
        self.assertTrue(completed_scene_reset(True, 26153, 0, False))


class CueSuppressionTests(unittest.TestCase):
    ENABLED={'cue_emission_enabled':True}
    def test_cues_play_on_good_bad_and_awful(self):
        self.assertIsNone(cue_suppression_reason(self.ENABLED,1_000_000,False))

    def test_cool_freestyle_mutes_note_cues(self):
        self.assertEqual(cue_suppression_reason(self.ENABLED,1_000_000,True),'cool_freestyle')

    def test_unvalidated_stage_wins_over_freestyle(self):
        self.assertEqual(cue_suppression_reason({'cue_emission_enabled':False},1_000_000,True),'pending_stage_validation')

    def test_poll_gap_still_suppresses_when_not_freestyling(self):
        self.assertEqual(cue_suppression_reason(self.ENABLED,CUE_POLL_GAP_NS+1,False),'poll_gap')
        self.assertIsNone(cue_suppression_reason(self.ENABLED,CUE_POLL_GAP_NS,False))


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
