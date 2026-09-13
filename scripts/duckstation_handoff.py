"""Read-only handoff observer for the pinned game's rendering paths.

The native-frame GPU probe 20260913T013919Z found the portrait absent at
VBlank 3996 and present at 3997. The first positive post-update marker was
in the VSync(2) wait targeting 3992, with swap count 1203. Presentation was
at swap count 1206. These are rendering stages, never a song/beat countdown.
Stage 2 normal and half-time probes in 20260913T015003Z confirm this sequence
at native frames 21686 and 22826. Stage 6 normal/short probes in
20260913T022324Z confirm native frames 85688 and 88574. The user authorized
Stages 3–5 for listening tests using the same sequence without visual checks.
"""
import struct
import time

WAIT_CALLERS = {1: 0x801c80f0, 2: 0x801c73e8, 3: 0x801c7784,
                4: 0x801c8b8c, 5: 0x801c6f34, 6: 0x801c7930}
VISUALLY_VERIFIED_STAGES = frozenset((1, 2, 6))
WAIT_PCS = (0x800356d0, 0x8003571c)
FIRST_WAIT = 0x800355f8
SECOND_WAIT = 0x8003561c


def word(data, offset=0):
    return struct.unpack_from('<I', data, offset)[0]


def marker_eligible(state):
    return (struct.unpack_from('<h', state, 0x8a)[0] > 0
            and struct.unpack_from('<h', state, 0x9e)[0] >= 0
            and struct.unpack_from('<h', state, 0x7a)[0] == 1)


def read_wait(ram, state, stage):
    """Accept only coherent samples inside this stage's native VSync loop."""
    if stage not in WAIT_CALLERS:return None
    regs=ram.read_registers();pc=ram.read_program_counter()
    sp=word(regs,116);ra=word(regs,124);target=word(regs,16)
    if (pc not in WAIT_PCS or ra not in (FIRST_WAIT,SECOND_WAIT)
            or not 0x80000000<=sp<=0x801fff80):return None
    stack=ram.read(sp,0x40)
    if word(stack,0x38)!=WAIT_CALLERS[stage]:return None
    native=word(ram.read(0x80057034,4))
    swap=word(ram.read(0x8009658c,4))
    after=ram.read_registers()
    if (ram.read_program_counter() not in WAIT_PCS or
            any(word(after,o)!=word(regs,o) for o in (16,116,124)) or
            ram.read(0x801c3640,0xb0)!=state or
            word(ram.read(0x80057034,4))!=native or
            word(ram.read(0x8009658c,4))!=swap or native not in (target-1,target)):
        return None
    return dict(native=native,target=target,second=ra==SECOND_WAIT,
                swap=swap,marker=marker_eligible(state),tick=word(state,12))


class HandoffFrames:
    """Require consecutive observed render cycles; never replay a missed cue."""
    def __init__(self):self.reset()

    def reset(self):
        self.native=None;self.tick=None;self.target=None;self.marker=None
        self.pending=None

    def feed(self, sample):
        native,tick=sample['native'],sample['tick']
        # The first VSync wait can already be satisfied when entered. Normal
        # polling then sees only every second native frame, still one complete
        # render cycle apart; target continuity below rejects a missed cycle.
        if (self.native is not None and not 0<=native-self.native<=2 or
                self.tick is not None and not 0<=tick-self.tick<=192):
            self.reset()
        self.native=native;self.tick=tick
        if sample['second'] and sample['target']!=self.target:
            contiguous=self.target is not None and sample['target']-self.target==2
            if not contiguous:self.pending=None
            if contiguous and self.marker is False and sample['marker']:
                self.pending=dict(native=sample['target']+5,swap=sample['swap']+3,
                                  source_tick=tick,source_target=sample['target'])
            self.target=sample['target'];self.marker=sample['marker']
        if not sample['marker']:self.pending=None
        if self.pending and native>=self.pending['native']:
            pending=self.pending;self.pending=None
            if native==pending['native'] and sample['swap']==pending['swap']:
                return dict(native_vsync=native,swap=sample['swap'],tick=tick,
                            source_tick=pending['source_tick'],source_target=pending['source_target'])
        return None


class HandoffObserver:
    def __init__(self, ram):
        self.ram=ram;self.frames=HandoffFrames();self.last_valid=None;self.stage=None

    def poll(self,state,stage,active=True):
        now=time.perf_counter_ns()
        if not active or stage not in WAIT_CALLERS or stage!=self.stage:
            self.frames.reset();self.last_valid=None;self.stage=stage
            if not active or stage not in WAIT_CALLERS:return None,None
        sample=read_wait(self.ram,state,stage)
        if self.last_valid is not None and now-self.last_valid>25_000_000:
            self.frames.reset()
        if sample is None:return None,None
        self.last_valid=now
        event=self.frames.feed(sample)
        if event:event.update(stage=stage,detected_ns=now,
                              visual_timing_verified=stage in VISUALLY_VERIFIED_STAGES)
        return event,sample
