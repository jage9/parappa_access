-- EXPERIMENTAL developer controller test; timing is not calibrated to pass.
-- Set aside at the user's request. Explicitly separate from normal play.
-- Uses ordinary button overrides at observed response reads; never edits
-- score, judgement, chart data or game code. Not loaded by the spoken menu.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local pad = PCSX.SIO0.slots[1].pads[1]
local buttons = PCSX.CONSTS.PAD.BUTTON
local names = {'TRIANGLE', 'CIRCLE', 'CROSS', 'SQUARE', 'L1', 'L1', 'R1', 'R1'}
local masks = {TRIANGLE = 0x10, CIRCLE = 0x20, CROSS = 0x40, SQUARE = 0x80, L1 = 0x04, R1 = 0x08}
local refs, held = {}, {}
local pending = {}
local delayFrames = stage1TestDelayFrames or 4
assert(delayFrames >= 0 and delayFrames <= 12, 'Test input delay outside 0..12 frames')
stage1RoundTest = refs
local frames, presses, done, completion = 0, 0, false, false
local previousMono = PCSX.settings.spu.Mono
local function u32(a) return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0]) end
local function s16(a) return tonumber(ffi.cast('int16_t*', ram + a - 0x80000000)[0]) end
local function cleanup()
    for name in pairs(held) do pad.clearOverride(buttons[name]) end
    held = {}
    pending = {}
    if stage1FrameTiming then stage1FrameTiming.stop() end
    PCSX.settings.spu.Mono = previousMono
end
local function finish(code, reason)
    if done then return end
    done = true
    cleanup()
    PCSX.log(string.format('ROUND_TEST_RESULT reason=%s frames=%d presses=%d score=%d\n',
        reason, frames, presses, s16(0x80091816)))
    PCSX.nextTick(function() PCSX.quit(code) end)
end
PCSX.settings.spu.Mono = true
stage1AudioFrames = 12000
local ok, err = pcall(function()
    Support.extra.dofile('../../scripts/stage1-audio.lua')
    assert(stage1CursorOptions, 'Audio initialization failed')
    local stop = stage1CursorOptions.stop
    stage1CursorOptions.stop = function()
        done = true
        cleanup()
        if stop then stop() end
    end
    stage1CursorOptions.ready = function()
        Support.extra.dofile('../../scripts/frame-timing.lua')
        assert(u32(0x801c8518) == 0x34040004 and u32(0x801c8494) == 0x0c0058d7,
            'Test result signatures changed')
        PCSX.log('ROUND_TEST_STARTED automated_input=true timing=observed_response_read delay_frames=' .. delayFrames ..
            ' release=first_game_poll max_hold_frames=6\n')
        refs.input = PCSX.addBreakpoint(0x801c7ee4, 'Exec', 4, 'Test observed controller result', function()
            local raw = tonumber(PCSX.getRegisters().GPR.n.v0)
            if not done and raw ~= 0 then
                PCSX.log(string.format('ROUND_TEST_INPUT frame=%d tick=%d mask=%08x\n',
                    frames, u32(0x801c364c), raw))
                for name in pairs(held) do
                    if bit.band(raw, masks[name]) ~= 0 then
                        pad.clearOverride(buttons[name])
                        held[name] = nil
                    end
                end
            end
        end)
        for _, address in ipairs({0x801c9398, 0x801c93f4, 0x801c9450}) do
            refs[#refs + 1] = PCSX.addBreakpoint(address, 'Exec', 4, 'Test response button', function()
                if done then return end
                local success, failure = pcall(function()
                    local r = PCSX.getRegisters().GPR.n
                    assert(tonumber(r.s1) == 0x801c3640 and u32(0x800943d0) == 0x801cfa54,
                        'Test left Stage 1 context')
                    local pointer = tonumber(r.v0)
                    assert(pointer >= 0x801cfa54 and pointer < 0x801cfa54 + 36 * 44,
                        'Response note outside verified table')
                    local lane = tonumber(ram[pointer - 0x80000000])
                    if lane == 0 or lane == 255 then return end
                    local name = assert(names[lane], 'Unknown test button')
                    assert(not held[name] and not pending[name], 'Overlapping test button press')
                    pending[name] = frames + delayFrames
                    presses = presses + 1
                    PCSX.log(string.format('ROUND_TEST_SCHEDULE frame=%d tick=%d button=%s\n',
                        frames, u32(0x801c364c), name))
                end)
                if not success then finish(2, tostring(failure)) end
            end)
        end
        refs.vsync = PCSX.Events.createEventListener('GPU::Vsync', function()
            if done then return end
            frames = frames + 1
            for name, release in pairs(held) do
                if frames >= release then pad.clearOverride(buttons[name]); held[name] = nil end
            end
            for name, due in pairs(pending) do
                if frames >= due then
                    pending[name] = nil
                    pad.setOverride(buttons[name])
                    held[name] = frames + 6
                    PCSX.log(string.format('ROUND_TEST_PRESS frame=%d tick=%d button=%s\n',
                        frames, u32(0x801c364c), name))
                end
            end
            if frames % 120 == 0 then
                PCSX.log(string.format('ROUND_TEST_PROGRESS frame=%d score=%d state_4e=%d\n',
                    frames, s16(0x80091816), s16(0x801c368e)))
            end
            if frames == 11999 then finish(3, 'timeout') end
        end)
        refs.failure = PCSX.addBreakpoint(0x801c8518, 'Exec', 4, 'Test failure result', function()
            if u32(0x800943d0) ~= 0x801cfa54 or tonumber(PCSX.getRegisters().GPR.n.v0) ~= 2 then
                finish(2, 'unexpected_failure_context'); return
            end
            finish(1, 'stage_not_cleared')
        end)
        refs.completion = PCSX.addBreakpoint(0x8001635c, 'Exec', 4, 'Test completion record', function()
            local r = PCSX.getRegisters().GPR.n
            if done or tonumber(r.ra) ~= 0x801c849c then return end
            completion = true
            PCSX.log(string.format('ROUND_TEST_COMPLETION stage=%d result=%d scalar=%d score=%d\n',
                tonumber(r.a0), tonumber(r.a1), tonumber(r.a2), tonumber(r.a3)))
        end)
        refs.dialog = PCSX.addBreakpoint(0x80026b94, 'Exec', 4, 'Test post-clear dialog', function()
            if not completion or done then return end
            PCSX.log('ROUND_TEST_DIALOG id=' .. tonumber(PCSX.getRegisters().GPR.n.a0) .. '\n')
            finish(0, 'completion_recorded')
        end)
    end
end)
if not ok then cleanup(); PCSX.log('ROUND_TEST_START_FAILED ' .. tostring(err) .. '\n'); PCSX.quit(2) end
