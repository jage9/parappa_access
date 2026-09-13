-- Bounded, read-only note-cursor capture. No audio or controller input.
-- PRIMARY/RESPONSE describe separate game cursors; see findings before reuse.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function log(s) print(s); PCSX.log(s .. '\n') end
local function u32(a)
    assert(a >= 0x80000000 and a <= 0x801ffffc, 'Invalid RAM address')
    return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0])
end
local function s16(a)
    return tonumber(ffi.cast('int16_t*', ram + a - 0x80000000)[0])
end
local names = {'TRIANGLE', 'CIRCLE', 'X', 'SQUARE', 'L1', 'L1', 'R1', 'R1'}
local options = stage1CursorOptions or {}
local profile = options.profile or Support.extra.dofile('../../scripts/stage-profiles.lua')[1]
assert(not options.note or profile.verified, 'Unverified stage cannot emit cues')
local function hasStage1Code()
    return u32(profile.entry) == 0x27bdffc8 and u32(profile.loop) == (profile.loopWord or 0x27bdffd0)
end
local function hasStage1Grid()
    return u32(0x800943d0) == profile.grid and u32(0x800943d4) == profile.count
end
local function hasStage1Context()
    return hasStage1Code() and hasStage1Grid()
end
local sites = {
    {profile.primary[1], 'PRIMARY', 0x94, 0x8c, 0x90, 1, 1},
    {profile.primary[2], 'PRIMARY', 0x94, 0x8c, 0x90, 1, 2},
    {profile.primary[3], 'PRIMARY', 0x98, 0x8e, 0x90, 2, 2},
    {profile.response[1], 'RESPONSE', 0xa4, 0x9e, 0xa2, 1, 1},
    {profile.response[2], 'RESPONSE', 0xa4, 0x9e, 0xa2, 1, 2},
    {profile.response[3], 'RESPONSE', 0xa8, 0xa0, 0xa2, 2, 2},
}
local refs = {breakpoints = {}}
stage1CursorProbe = refs
local loadState = options.loadState ~= false
local keepGameRunning = options.keepGameRunning == true
local frameLimit = options.frames or 1800
assert(frameLimit >= 0 and frameLimit <= 18000, 'Capture limit outside 0..18000')
-- Zero selects interactive play; detailed note logging still has a budget.
local frame, primary, response, blanks = 0, 0, 0, 0
local detailDeadline = 18000
local done, detached, cuesStopped = false, false, false
local last = {}
refs.isActive = function() return not done end
refs.resetResearchWindow = function()
    if not done and frameLimit == 0 then detailDeadline = frame + 18000 end
end
local function removeListener(listener)
    if listener then pcall(function() listener:remove() end) end
end
local function detachHooks()
    if detached then return end
    detached = true
    -- Keep breakpoint objects rooted, but disable them before leaving the
    -- overlay.  Freeing a breakpoint from its own callback is unsafe.
    for _, breakpoint in ipairs(refs.breakpoints) do
        pcall(function() breakpoint:disable() end)
    end
    -- EventBus traverses live listener nodes. Defer freeing them until the
    -- current callback has returned, including the Quitting callback itself.
    PCSX.nextTick(function()
        removeListener(refs.vsync)
        removeListener(refs.quitting)
        if refs.lifecycle then
            for _, listener in ipairs(refs.lifecycle) do removeListener(listener) end
        end
    end)
end
local function stopCues()
    if cuesStopped then return end
    cuesStopped = true
    if options.stop then options.stop() end
end
local function finish(code, message)
    if done then return end
    done = true
    detachHooks()
    stopCues()
    log(message)
    if keepGameRunning then return end
    PCSX.nextTick(function() PCSX.quit(code) end)
end
PCSX.nextTick(function()
    local ok, err = pcall(function()
        PCSX.pauseEmulator()
        assert(PCSX.settings.emulator.Debug.Debug and not PCSX.settings.emulator.Dynarec,
            'Launch with -Debugger')
        if loadState then
            local file = Support.File.open(options.statePath or '../../logs/stage1-gameplay.sstate')
            assert(not file:failed(), 'Run prepare-stage1.lua first')
            PCSX.loadSaveState(file); file:close()
        end
        assert(hasStage1Code(), 'Stage 1 signature mismatch')
        assert(hasStage1Grid(), 'Button-grid table mismatch')
        refs.lifecycle = {}
        for _, event in ipairs({'ExecutionFlow::Reset', 'ExecutionFlow::SaveStateLoaded', 'IsoMounted'}) do
            refs.lifecycle[#refs.lifecycle + 1] = PCSX.Events.createEventListener(event, function()
                finish(keepGameRunning and 0 or 2,
                    keepGameRunning and 'CURSOR_CAPTURE_DETACHED execution_context_changed'
                        or 'CURSOR_CAPTURE_STOPPED execution_context_changed')
            end)
        end
        refs.quitting = PCSX.Events.createEventListener('Quitting', function()
            done = true
            detachHooks()
            stopCues()
        end)
        for _, site in ipairs(sites) do
            local spec = site
            assert(u32(spec[1]) == 0x80430000, 'Cursor instruction mismatch')
            refs.breakpoints[#refs.breakpoints + 1] = PCSX.addBreakpoint(
                spec[1], 'Exec', 4, spec[2] .. ' grid-byte consumption', function()
                if done then return end
                local success, failure = pcall(function()
                    local regs = PCSX.getRegisters().GPR.n
                    local state = tonumber(regs.s1)
                    assert(state == 0x801c3640, 'Unexpected scene state')
                    assert(hasStage1Context(), 'Stage 1 context changed')
                    assert(bit.band(u32(state), 8) ~= 0, 'Cursor outside subdivision event')
                    assert(s16(state + 0x8a) == spec[7] and s16(state + spec[5]) == spec[6],
                        'Unexpected cursor gate')
                    local pointer = u32(state + spec[3])
                    local offset = pointer - profile.grid
                    assert(offset >= 0 and offset < profile.count * 44 and
                        (offset % 44 == 4 or offset % 44 == 24), 'Grid outside table')
                    local index = s16(state + spec[4])
                    assert(index >= 0 and index < 19, 'Invalid cursor index')
                    local address = tonumber(regs.v0)
                    assert(address == pointer + index, 'Cursor address mismatch')
                    local lane = tonumber(ram[address - 0x80000000])
                    if lane == 0 or lane == 255 then blanks = blanks + 1; return end
                    assert(names[lane], 'Unknown grid button')
                    local tick = u32(state + 0x0c)
                    local key = string.format('%d:%08x', tick, address)
                    assert(last[spec[2]] ~= key, 'Duplicate cursor note')
                    last[spec[2]] = key
                    -- Call directly at the game's existing primary byte read; never queue cues.
                    if spec[2] == 'PRIMARY' and options.note then options.note(names[lane]) end
                    if spec[2] == 'PRIMARY' then primary = primary + 1 else response = response + 1 end
                    if frame <= detailDeadline then
                        log(string.format('CURSOR_NOTE stream=%s frame=%d tick=%d lane=%d button=%s address=%08x pc=%08x stage=%d',
                            spec[2], frame, tick, lane, names[lane], address, spec[1], profile.stage))
                    end
                end)
                if not success then finish(2, 'CURSOR_CAPTURE_FAILED ' .. tostring(failure)) end
            end)
        end
        refs.vsync = PCSX.Events.createEventListener('GPU::Vsync', function()
            if done then return end
            frame = frame + 1
            if not hasStage1Context() or
                (keepGameRunning and bit.band(u32(0x800916d0), 0xffff) ~= 0) then
                finish(keepGameRunning and 0 or 2,
                    keepGameRunning and 'CURSOR_CAPTURE_DETACHED execution_context_changed'
                        or 'CURSOR_CAPTURE_STOPPED execution_context_changed')
                return
            end
            if frameLimit > 0 and frame == frameLimit then
                finish(primary > 0 and response > 0 and 0 or 3,
                    string.format('CURSOR_CAPTURE_COMPLETE frames=%d primary=%d response=%d blanks=%d',
                        frame, primary, response, blanks))
            end
            if frameLimit == 0 and frame == detailDeadline then
                log('CURSOR_DETAIL_LIMIT_REACHED gameplay_and_cues_continue')
            end
        end)
        if loadState then
            log('CURSOR_STATE_LOADED audio=' .. tostring(options.note ~= nil))
        else
            log('CURSOR_CONTEXT_ATTACHED audio=' .. tostring(options.note ~= nil))
        end
        if options.ready then options.ready() end
        if options.paused then log('CURSOR_READY paused=true') else PCSX.resumeEmulator() end
    end)
    if not ok then
        -- Native attach pauses for setup; an attach failure must hand the
        -- live game back to the user in its running state.
        if keepGameRunning then pcall(function() PCSX.resumeEmulator() end) end
        finish(2, 'CURSOR_CAPTURE_FAILED ' .. tostring(err))
    end
end)
