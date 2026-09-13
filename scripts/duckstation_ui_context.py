"""Read-only active card-manager context from the pinned game's live stack.

The guard follows two verified VSync frames, not cached menu object values.
It never drives input or supplies rhythm cues.
"""
import struct


def word(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def decode_opening_wait(pc, registers, stack):
    if len(registers)!=128 or len(stack)<0x54 or pc not in (0x800356D0,0x8003571C):
        return False
    sp=word(registers,116);ra=word(registers,124)
    return (sp%4==0 and 0x80000000<=sp<=0x80200000-0x54
            and ra in (0x800355F8,0x8003561C) and word(stack,0x18)==ra
            and word(stack,0x34)==0x801C3640 and word(stack,0x50)==0x801C3640
            and word(stack,0x38)==0x801C44AC)


def decode_title_wait(pc, registers, stack):
    if len(registers)!=128 or len(stack)<0x54 or pc not in (0x800356D0,0x8003571C):
        return None
    sp=word(registers,116);ra=word(registers,124)
    if sp%4 or not 0x80000000<=sp<=0x80200000-0x54:
        return None
    if (ra not in (0x800355F8,0x8003561C) or word(stack,0x18)!=ra
            or word(stack,0x34)!=0x801C3640 or word(stack,0x38)!=0x801C4D74
            or word(stack,0x50) not in (0,1)):
        return None
    return sp+0x50


def decode_practice_wait(pc, registers, stack):
    if len(registers)!=128 or len(stack)<0x40 or pc not in (0x800356D0,0x8003571C):
        return False
    sp=word(registers,116);ra=word(registers,124)
    if sp%4 or not 0x80000000<=sp<=0x801FFFC0:
        return False
    if ra not in (0x8003561C,0x800355F8) or word(stack,0x18)!=ra or word(stack,0x34)!=0x801C3640:
        return False
    caller=word(stack,0x38)
    if caller in (0x800277DC,0x800279DC,0x80027D34,0x80027EA0):
        return True
    return (caller==0x8002773C and len(stack)>=0x5c and sp+0x5c<=0x80200000
            and word(stack,0x54)==0x801C3640
            and word(stack,0x58) in (0x80027854,0x80027D9C,0x80027E58,0x80027E80))


def decode_card_wait(pc, registers, stack):
    if len(registers) != 128 or len(stack) < 0x40:
        return None
    if pc not in (0x800356D0, 0x8003571C):
        return None
    sp = word(registers, 29 * 4)
    if not 0x80000000 <= sp <= 0x801FFFC0 or sp % 4:
        return None
    # 800356A8 saves its caller at +18; its parent 80035560 saves
    # the card-manager return at +38 and mode/object in saved S0/S1.
    if (word(registers, 31 * 4) != 0x8003561C
            or word(stack, 0x18) != 0x8003561C
            or word(stack, 0x38) != 0x800190F4):
        return None
    mode, state = word(stack, 0x30), word(stack, 0x34)
    if not 2 <= mode <= 22 or not 0x80000000 <= state <= 0x801FFFFC:
        return None
    return (mode, state)


class CardContext:
    def __init__(self, ram):
        self.ram = ram
        self.modal = None
        self.scene = None
        self.practice = False
        self.practice_wait = None
        self.title_selector = None
        self.opening = False
        self.valid_code = all(word(ram.read(address, 4), 0) == value for address, value in (
            (0x80018FB0, 0x27BDFFC8),
            (0x800190EC, 0x0C00D558),
            (0x80035570, 0x27BDFFE0),
            (0x800356A8, 0x27BDFFE0),
            (0x80035614, 0x0C00D5AA),
            (0x80026B94, 0x27BDFFC8),
            (0x80026DC0, 0x0C00D558),
        ))

    def poll(self):
        self.modal = None
        self.scene = None
        self.practice = False
        self.practice_wait = None
        self.title_selector = None
        self.opening = False
        if not self.valid_code or not getattr(self.ram, 'cpu_context_verified', False):
            return None
        first = self.ram.read_registers()
        pc = self.ram.read_program_counter()
        sp = word(first, 29 * 4)
        if pc not in (0x800356D0, 0x8003571C) or not 0x80000000 <= sp <= 0x801FFFC0:
            return None
        stack = self.ram.read(sp, min(0x70, 0x80200000-sp))
        second = self.ram.read_registers()
        second_pc = self.ram.read_program_counter()
        if first[116:128] != second[116:128] or pc != second_pc:
            return None
        if (decode_opening_wait(pc,second,stack)
                and self.ram.read(0x801c4d20,8)==bytes.fromhex('1000a58f1516070c')
                and word(self.ram.read(0x801c44a4,4),0)==0x0C00D558):
            self.opening=True
        title=decode_title_wait(pc,second,stack)
        if (title is not None and self.ram.read(0x801c4d20,8)==bytes.fromhex('1000a58f1516070c')
                and word(self.ram.read(0x801c4d6c,4),0)==0x0C00D558):
            self.title_selector=title
        if decode_practice_wait(pc,second,stack):
            caller=word(stack,0x38)
            self.practice=(word(self.ram.read(0x8002776c,4),0)==0x27BDFF58
                           and word(self.ram.read(0x80023618,4),0)==0x27BDFFC0
                           and word(self.ram.read(0x800916d0,4),0)&0xffff==0
                           and word(self.ram.read(caller-8,4),0)==0x0C00D558)
            if caller==0x8002773C:
                parent=word(stack,0x58)
                self.practice=(self.practice and word(self.ram.read(parent-8,4),0)==0x0C009DBB
                               and word(self.ram.read(0x800276ec,4),0)==0x27BDFFE0
                               and word(self.ram.read(0x8002770c,4),0)==0xAFBF0018)
            if self.practice:self.practice_wait=caller
        from duckstation_scene_speech import decode_scene_wait
        scene = decode_scene_wait(pc, second, stack)
        if scene is not None:
            from duckstation_profiles import PROFILES
            entry = PROFILES[min(scene,6)]['entry']
            marker = entry-0x2a0
            parent = word(stack,0x68)
            wait = word(stack,0x38)
            if (word(self.ram.read(entry,4),0)==0x27BDFFC8
                    and self.ram.read(marker,8)==bytes.fromhex('d0ffbd272400b5af')
                    and word(self.ram.read(wait-8,4),0)==0x0C00D558
                    and (word(self.ram.read(parent-4,4),0)==0x2406FFFF if scene==7
                         else word(self.ram.read(parent-12,4),0)==0x00003021)
                    and word(self.ram.read(parent-8,4),0)==(0x0C000000|((marker>>2)&0x03ffffff))):
                self.scene=scene
        if (word(second, 31*4)==0x8003561C and word(stack,0x18)==0x8003561C
                and word(stack,0x38)==0x80026DC8):
            descriptor=word(stack,0x34)
            if 0x80054500<=descriptor<=0x800545F0 and descriptor%4==0:
                state=word(self.ram.read(descriptor+0x10,4),0)
                self.modal=(word(second,19*4),state)
        card = decode_card_wait(pc, second, stack)
        if card is not None and card[0] == 17:
            # The card wrapper stores its entry variant before invoking the
            # generic manager. Only variant 3 is the verified high-score flow.
            if (word(second,28*4)!=0x8006EA40
                    or word(self.ram.read(0x80019218,4),0)!=0xAF9002DC
                    or word(self.ram.read(0x8006ED1C,4),0)!=3):
                return None
        return card
