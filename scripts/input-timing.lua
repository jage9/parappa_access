-- Passive timing of Redux-received keyboard events during verified stage play.
-- Times are callback-receipt times in the emulator process, not hardware times.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local profiles = Support.extra.dofile('../../scripts/stage-profiles.lua')
local function u32(address)
    return tonumber(ffi.cast('uint32_t*', ram + address - 0x80000000)[0])
end

-- PCSX-Redux's default keyboard bindings are SDL scancodes: D, X, Z, S, Q, R.
-- These are physical-key mappings verified against the pinned local Redux source.
local keys = {
    [7] = 'CIRCLE',
    [27] = 'X',
    [29] = 'SQUARE',
    [22] = 'TRIANGLE',
    [20] = 'L1',
    [21] = 'R1',
}
local MOD_CTRL_ALT_GUI = 0x0fc0
local MAX_EVENTS = 4096

local refs = {
    listeners = {},
    records = {},
    held = {},
    recordedHeld = {},
    running = false,
    total = 0,
    dropped = 0,
    maxEvents = MAX_EVENTS,
}
inputTimingRefs = refs -- Keep listeners and state reachable for the session.

local function contextProfile()
    local p = stageScoreContext
    if type(p) ~= 'table' or p.verified ~= true then return nil end
    local expected = profiles[p.stage]
    if not expected or expected.verified ~= true then return nil end
    if p.entry ~= expected.entry or p.loop ~= expected.loop or
        p.grid ~= expected.grid or p.count ~= expected.count or
        (p.loopWord or 0x27bdffd0) ~= (expected.loopWord or 0x27bdffd0) then
        return nil
    end
    if u32(expected.entry) ~= 0x27bdffc8 or
        u32(expected.loop) ~= (expected.loopWord or 0x27bdffd0) or
        u32(0x800943d0) ~= expected.grid or
        u32(0x800943d4) ~= expected.count or
        u32(0x800916d0) % 0x10000 ~= 0 then
        return nil
    end
    return expected
end

local function hostNsText(value)
    -- Preserve LuaJIT's exact uint64 decimal spelling when luv returns cdata.
    local s = tostring(value):gsub('ULL$', ''):gsub('LL$', '')
    if s:match('^%d+$') then return s end
    return string.format('%.0f', tonumber(value))
end

local function append(profile, button, action, scancode, hostNs)
    if refs.total >= MAX_EVENTS then
        refs.dropped = refs.dropped + 1
        return false
    end
    refs.total = refs.total + 1
    refs.records[#refs.records + 1] = {
        sequence = refs.total,
        stage = profile.stage,
        button = button,
        action = action,
        scancode = scancode,
        hostNs = hostNsText(hostNs),
        tick = u32(0x801c364c),
    }
    return true
end

local function flush(reason)
    local records = refs.records
    local lines = {string.format(
        'INPUT_TIMING_FLUSH reason=%s buffered=%d total=%d dropped=%d source=redux_keyboard_event\n',
        reason, #records, refs.total, refs.dropped)}
    for i = 1, #records do
        local r = records[i]
        lines[#lines + 1] = string.format(
            'INPUT_KEY source=redux_keyboard_event time_basis=emulator_callback stage=%d button=%s action=%s host_ns=%s tick=%d scancode=%d sequence=%d\n',
            r.stage, r.button, r.action, r.hostNs, r.tick, r.scancode, r.sequence)
    end
    -- Logging happens only after execution pauses or Redux begins quitting.
    PCSX.log(table.concat(lines))
    refs.records = {}
    return #records
end

local function onKeyboard(event)
    local scancode = event.scancode
    local button = keys[scancode]
    if not button then return end
    local action = event.action
    if action ~= 0 and action ~= 1 then return end

    -- Capture the Redux callback receipt time before validating game state.
    local hostNs = luv.hrtime()
    if action == 0 then
        local wasHeld = refs.held[scancode]
        local wasRecorded = refs.recordedHeld[scancode]
        refs.held[scancode] = nil
        refs.recordedHeld[scancode] = nil
        if not wasHeld or not wasRecorded or
            bit.band(event.mods or 0, MOD_CTRL_ALT_GUI) ~= 0 or not refs.running then
            return
        end
        local profile = contextProfile()
        if profile then append(profile, button, 'up', scancode, hostNs) end
        return
    end

    -- SDL can send repeated key-downs while held; represent one press only.
    if refs.held[scancode] then return end
    refs.held[scancode] = true
    if bit.band(event.mods or 0, MOD_CTRL_ALT_GUI) ~= 0 or not refs.running then return end
    local profile = contextProfile()
    if profile and append(profile, button, 'down', scancode, hostNs) then
        refs.recordedHeld[scancode] = true
    end
end

local function onRun()
    refs.running = true
end

local function onPause()
    refs.running = false
    flush('pause')
end

local function onQuitting()
    refs.running = false
    flush('quitting')
end

refs.contextProfile = contextProfile
refs.onKeyboard = onKeyboard
refs.onRun = onRun
refs.onPause = onPause
refs.onQuitting = onQuitting
refs.listeners[#refs.listeners + 1] = PCSX.Events.createEventListener('Keyboard', onKeyboard)
refs.listeners[#refs.listeners + 1] = PCSX.Events.createEventListener('ExecutionFlow::Run', onRun)
refs.listeners[#refs.listeners + 1] = PCSX.Events.createEventListener('ExecutionFlow::Pause', onPause)
refs.listeners[#refs.listeners + 1] = PCSX.Events.createEventListener('Quitting', onQuitting)

return refs
