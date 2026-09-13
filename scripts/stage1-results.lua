-- Bounded, read-only Stage 1 result research. Install after the state loads.
-- No per-note, miss, or rank announcements and no controller input.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function u32(address)
    return tonumber(ffi.cast('uint32_t*', ram + address - 0x80000000)[0])
end
local function s16(address)
    return tonumber(ffi.cast('int16_t*', ram + address - 0x80000000)[0])
end
local sequence = stage1ResultSequence or 0
stage1ResultRefs = {}
local refs = stage1ResultRefs
local frame, entries, stopped = 0, 0, false
local closed = false
local researchDeadline = 18000
local peakScore = 0
local scene = 0x801c3640
local inputBreakpoint
local inputTransitions = 0
local inputStopped = false
local previousInputMask
local function disableInputBreakpoint()
    if inputStopped then return end
    inputStopped = true
    if inputBreakpoint then
        pcall(function() inputBreakpoint:disable() end)
    end
end
local function inputSitePresent()
    return u32(0x801c7edc) == 0x0c00d544 and
        u32(0x801c7ee0) == 0x34040001 and
        u32(0x801c7ee4) == 0x00402021
end
local function context()
    return u32(0x800943d0) == 0x801cfa54 and u32(0x801c8518) == 0x34040004
end
local function log(kind, details)
    if stopped then return end
    entries = entries + 1
    PCSX.log(string.format('RESULT_RESEARCH kind=%s frame=%d tick=%d score_raw=%d state_4e=%d %s\n',
        kind, frame, u32(scene + 0x0c), s16(0x80091816), s16(scene + 0x4e), details or ''))
    if entries >= 2048 then
        stopped = true
        disableInputBreakpoint()
        PCSX.log('RESULT_RESEARCH_STOP reason=entry_limit\n')
    end
end
local function stopResearch()
    if not stopped then log('stop', 'entries=' .. entries) end
    stopped = true
    disableInputBreakpoint()
end
refs.stop = function()
    stopResearch()
    closed = true
end
local function probe(key, address, callback, kind, size)
    refs[key] = PCSX.addBreakpoint(address, kind or 'Exec', size or 4, 'Result research ' .. key, function(...)
        if stopped then return end
        if not context() then refs.stop(); return end
        local ok, err = pcall(callback, PCSX.getRegisters().GPR.n, ...)
        if not ok then
            log('error', key .. ' ' .. tostring(err))
            disableInputBreakpoint()
            stopped = true
            return false
        end
    end)
end
assert(u32(0x801c8518) == 0x34040004, 'Stage 1 result-path signature mismatch')
assert(tonumber(ram[0x6eb00]) == 0x25 and tonumber(ram[0x6eb01]) == 0x64 and
    tonumber(ram[0x6eb02]) == 0, 'Score formatter is not the verified integer format')
assert(u32(0x801c82f8) == 0x3c128009 and u32(0x801c8494) == 0x0c0058d7 and
    u32(0x801c8498) == 0x02a03021 and u32(0x80024fc4) == 0x84421816 and
    u32(0x80026b94) == 0x27bdffc8 and u32(0x80026df8) == 0x8fbf0034,
    'Stage 1 research signature mismatch')
log('start', 'version=3 disc=SCUS-94183 identity=docs/disc-metadata.md detailed=' .. tostring(stage1ResultDetailedResearch ~= false))
local previousState
local publish
refs.attempt = PCSX.addBreakpoint(0x801c7a60, 'Exec', 4, 'Reset attempt peak score', function()
    if closed then return end
    previousInputMask = nil
    if nativeObserver and nativeObserver.setHint then nativeObserver.setHint('') end
    if context() then
        stageScoreContext = Support.extra.dofile('../../scripts/stage-profiles.lua')[1]
        peakScore = 0
        entries, stopped = 0, false
        researchDeadline = frame + 18000
        inputTransitions = 0
        if inputBreakpoint and inputSitePresent() then
            inputStopped = false
            inputBreakpoint:enable()
        end
        if stage1CursorProbe and stage1CursorProbe.resetResearchWindow then
            stage1CursorProbe.resetResearchWindow()
        end
        log('attempt_start', 'research_budget_frames=18000 input_limit=512')
    end
end)
if inputSitePresent() then
    inputBreakpoint = PCSX.addBreakpoint(0x801c7ee4, 'Exec', 4, 'Observe received controller mask', function()
        if stopped or closed or inputStopped then return end
        if not context() or not inputSitePresent() then
            refs.stop()
            return
        end
        local ok, err = pcall(function()
            local hostNs = tonumber(luv.hrtime())
            local registers = PCSX.getRegisters().GPR.n
            local mask = tonumber(registers.v0) or 0
            if mask == previousInputMask then return end
            previousInputMask = mask
            inputTransitions = inputTransitions + 1
            log('input', string.format('mask=%08x transition=%d host_ns=%.0f', mask, inputTransitions, hostNs))
            if inputTransitions >= 512 then
                disableInputBreakpoint()
                PCSX.log('RESULT_INPUT_STOP reason=transition_limit transitions=512\n')
            end
        end)
        if not ok then
            log('error', 'input ' .. tostring(err))
            disableInputBreakpoint()
            stopped = true
            return false
        end
    end)
    refs.input = inputBreakpoint
else
    inputStopped = true
    PCSX.log('RESULT_INPUT_DISABLED reason=signature_mismatch\n')
end
refs.vsync = PCSX.Events.createEventListener('GPU::Vsync', function()
    if closed then return end
    if not context() then refs.stop(); return end
    peakScore = math.max(peakScore, s16(0x80091816))
    frame = frame + 1
    if stopped then return end
    local state = string.format('app=%d mode=%d scene_score_raw=%d score_raw=%d state_4e=%d',
        s16(0x800916d0), s16(0x800916da), u32(scene + 0x30),
        s16(0x80091816), s16(scene + 0x4e))
    if state ~= previousState then log('state_change', state); previousState = state end
    if frame >= researchDeadline then stopResearch() end
end)
refs.gameplay_return = PCSX.addBreakpoint(0x801c82f8, 'Exec', 4, 'Stage 1 gameplay result', function()
    if closed or not context() then return end
    local result = tonumber(PCSX.getRegisters().GPR.n.v0)
    log('gameplay_return', string.format('return_raw=%d', result))
    if result == 1 and s16(0x800916d0) == 0 then
        if nativeObserver and nativeObserver.setHint then nativeObserver.setHint('') end
        publish('clear')
    end
end)
-- Observe after the caller's delay slot has populated a2.
probe('completion_record', 0x8001635c, function(r)
    if tonumber(r.ra) ~= 0x801c849c then return end
    log('completion_record', string.format('stage_raw=%d result_raw=%d scalar_raw=%d score_arg_raw=%d',
        tonumber(r.a0), tonumber(r.a1), tonumber(r.a2), tonumber(r.a3)))
end)
local previousScore, consumerAddress
local consumers = {}
if stage1ResultDetailedResearch ~= false then
    probe('score_copy', 0x80024fc4, function(r)
        local address = tonumber(r.a0) + 0x30
        assert(address >= 0x80000000 and address <= 0x801ffffc, 'Score object outside RAM')
        local score = s16(0x80091816)
        if score ~= previousScore then
            log('score_copy', string.format('destination=%08x value=%d', address, score))
            previousScore = score
        end
        if consumerAddress then return end
        consumerAddress = address
        -- Only one four-byte object field; report each reader when its value changes.
        probe('score_consumer', address, function(registers)
            local pc = tonumber(PCSX.getRegisters().pc)
            local value = u32(address)
            if consumers[pc] == value then return end
            consumers[pc] = value
            log('score_consumer', string.format('pc=%08x ra=%08x address=%08x value=%d',
                pc, tonumber(registers.ra), address, value))
        end, 'Read', 4)
    end)
end
probe('dialog_enter', 0x80026b94, function(r)
    log('dialog_enter', string.format('id_raw=%d arg_raw=%d caller=%08x',
        tonumber(r.a0), tonumber(r.a1), tonumber(r.ra)))
end)
refs.dialog_return = PCSX.addBreakpoint(0x80026df8, 'Exec', 4, 'Result dialog return', function()
    if closed then return end
    if not context() then refs.stop(); return end
    if nativeObserver and nativeObserver.setHint then nativeObserver.setHint('') end
    log('dialog_return', string.format('return_raw=%d', tonumber(PCSX.getRegisters().GPR.n.v0)))
end)
local phrases = {}
if stage1ResultDetailedResearch ~= false then
    probe('phrase_table', 0x801ce0d8, function(r, address)
        local id = math.floor((tonumber(address) - 0x801ce0d8) / 4)
        if id < 0 or id >= 91 or phrases[id] then return end
        phrases[id] = true
        log('phrase_table_read', string.format('id_raw=%d pc=%08x ra=%08x',
            id, tonumber(PCSX.getRegisters().pc), tonumber(r.ra)))
    end, 'Read', 91 * 4)
end
publish = function(kind)
    sequence = math.max(sequence, stage1ResultSequence or 0) + 1
    stage1ResultSequence = sequence
    local score = s16(0x80091816)
    peakScore = math.max(peakScore, score)
    PCSX.log(string.format('STAGE_RESULT kind=%s sequence=%d score=%d peak_score=%d\n', kind, sequence, score, peakScore))
    local file = assert(io.open('../../logs/demo-result.json', 'w'))
    file:write(string.format('{"sequence":%d,"kind":"%s","score":%d,"peak_score":%d}', sequence, kind, score, peakScore))
    file:close()
end
refs.reportScore = function()
    if closed or not context() then
        PCSX.log('SCORE_UNAVAILABLE Stage 1 context changed\n')
        return
    end
    publish('score')
    return true
end
stage1ResultRefs.failure = PCSX.addBreakpoint(0x801c8518, 'Exec', 4, 'Stage 1 failure menu', function()
    if closed then return end
    local ok, err = pcall(function()
        local regs = PCSX.getRegisters().GPR.n
        assert(u32(0x800943d0) == 0x801cfa54, 'Stage 1 result context changed')
        if tonumber(regs.v0) ~= 2 or s16(0x800916d0) ~= 0 then return end
        if nativeObserver and nativeObserver.setHint then
            nativeObserver.setHint('X Retry. D Leave.')
        end
        publish('failure')
    end)
    if not ok then
        PCSX.log('STAGE_RESULT_DISABLED ' .. tostring(err) .. '\n')
        return false
    end
end)
