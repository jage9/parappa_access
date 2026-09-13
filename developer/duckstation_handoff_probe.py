"""Bounded read-only render-pass/GPU inspection; never used by normal play."""
import struct
import time


def capture_native_frames(ram,capture,screenshots,command,reach,key,connect,disconnect,monitor,start_tick=2820,end_tick=2860):
    """Inspect each native VBlank, including the middle of VSync(2)."""
    deadline=time.monotonic()+70
    while time.monotonic()<deadline:
        tick=struct.unpack('<I',ram.read(0x801c364c,4))[0]
        if start_tick<=tick<100000:break
        time.sleep(.005)
    else:raise TimeoutError('Native-frame handoff window not reached')
    monitor.diagnostic_paused=True
    connect()
    last_frame=None
    for attempt in range(32):
        assert command('s').startswith(('T','S'))
        reach(0x80035734,timeout=5)
        native=struct.unpack('<I',ram.read(0x80057034,4))[0]
        if native==last_frame:continue
        last_frame=native
        state=ram.read(0x801c3640,0xb0)
        regs=ram.read_registers()
        stack=ram.read(struct.unpack_from('<I',regs,116)[0],0x80)
        before=set(screenshots.glob('*.png'))
        key(0x79)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            added=set(screenshots.glob('*.png'))-before
            if added:break
            time.sleep(.025)
        else:raise TimeoutError('Native-frame GPU screenshot did not complete')
        capture.record_event('handoff_native_frame',native_vsync=native,state_hex=state.hex(),
            stage=monitor.current_stage,target=start_tick,
            registers_hex=regs.hex(),stack_hex=stack.hex(),
            swap_state_hex=ram.read(0x8009658c,8).hex(),
            screenshots=[str(p) for p in sorted(added)])
        if struct.unpack_from('<I',state,12)[0]>=end_tick:break
    else:raise AssertionError('Native-frame capture budget exhausted')
    disconnect();time.sleep(.06);monitor.diagnostic_paused=False


def capture_handoffs(ram,capture,screenshots,command,reach,key,connect,disconnect,monitor,late_only=False,early_only=False):
    # Existing campaign evidence: short and long call/response sections.
    # These targets schedule diagnostic capture only, never accessibility cues.
    deadline=time.monotonic()+180
    windows=((10670,10728),) if late_only else ((2795,2855),(10670,10728))
    if early_only:windows=windows[:1]
    for start_tick,end_tick in windows:
        while time.monotonic()<deadline:
            tick=struct.unpack('<I',ram.read(0x801c364c,4))[0]
            if monitor.retry_active:raise RuntimeError('Diagnostic play reached Retry before the next capture window')
            if start_tick<=tick<100000:break
            time.sleep(.005)
        else:raise TimeoutError('Handoff capture window not reached')
        monitor.diagnostic_paused=True
        connect()
        assert ram.read(0x80024744,4)==bytes.fromhex('90ffbd27'),'HUD signature mismatch'
        capture.record_event('handoff_frame_probe_started',target=start_tick,
                             limitation='Debugger pauses invalidate realtime audio/input latency')
        hud_history=[]
        for frame in range(40):
            # Step off a previous breakpoint before arming the same address.
            assert command('s').startswith(('T','S'))
            reach(0x80024744,timeout=5)
            state=ram.read(0x801c3640,0xb0)
            tick=struct.unpack_from('<I',state,12)[0]
            hud_vsync=struct.unpack('<I',ram.read(0x80057034,4))[0]
            reach(0x801c80f0,timeout=5)
            rendered_state=ram.read(0x801c3640,0xb0)
            present_vsync=struct.unpack('<I',ram.read(0x80057034,4))[0]
            completed_vsync=struct.unpack('<I',ram.read(0x80055f74,4))[0]
            before=set(screenshots.glob('*.png'))
            added=set()
            for attempt in range(2):
                key(0x79)
                wait_until=time.monotonic()+3
                while time.monotonic()<wait_until:
                    added=set(screenshots.glob('*.png'))-before
                    if added:break
                    time.sleep(.025)
                if added:break
                capture.record_event('handoff_screenshot_retry',target=start_tick,ordinal=frame,attempt=attempt)
            if not added:raise TimeoutError('GPU screenshot did not complete while debugger-paused')
            capture.record_event('handoff_render_pass',target=start_tick,ordinal=frame,tick=tick,
                pc=0x801c80f0,state_hex=state.hex(),post_wait_state_hex=rendered_state.hex(),
                hud_vsync=hud_vsync,present_vsync=present_vsync,completed_vsync=completed_vsync,
                previous_hud_state_hex=hud_history[-1].hex() if hud_history else None,
                two_passes_prior_state_hex=hud_history[-2].hex() if len(hud_history)>=2 else None,
                screenshots=[str(p) for p in sorted(added)],
                interpretation='Completed output at pre-submit VSync return; observed first marker matches two HUD passes earlier')
            hud_history.append(state)
            if tick>=end_tick:break
        else:raise AssertionError('Handoff adjacent-frame budget exhausted')
        disconnect()
        # Let the observer see resumed updates before re-enabling its normal
        # stall guard; a deliberate debugger stop must not disable this driver.
        time.sleep(.06)
        monitor.diagnostic_paused=False
