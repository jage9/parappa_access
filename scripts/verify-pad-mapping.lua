-- Isolated mapping test. Reload before each trial and pause at PadRead return,
-- BEFORE the game processes the pressed button. This does not play the stage.
local pad = PCSX.SIO0.slots[1].pads[1]
local buttons = PCSX.CONSTS.PAD.BUTTON
local trials = {'CIRCLE', 'CROSS', 'SQUARE', 'TRIANGLE', 'L1', 'R1'}
local expected = {0x20, 0x40, 0x80, 0x10, 0x04, 0x08}
local index, frames, busy = 0, 0, false
local refs = {}
padMappingTest = refs
local function log(s) print(s); PCSX.log(s) end
local function release()
    for _, name in ipairs(trials) do pad.clearOverride(buttons[name]) end
end
local function fail(err)
    release(); log('PAD_MAPPING_FAILED ' .. tostring(err)); PCSX.quit(2)
end
local function nextTrial()
    local ok, err = pcall(function()
        PCSX.pauseEmulator()
        release()
        index = index + 1
        if index > #trials then log('PAD_MAPPING_COMPLETE trials=6'); PCSX.quit(0); return end
        local file = Support.File.open('../../logs/stage1-gameplay.sstate')
        assert(not file:failed(), 'Run prepare-stage1.lua first')
        PCSX.loadSaveState(file); file:close()
        frames, busy = 0, false
        pad.setOverride(buttons[trials[index]])
        PCSX.resumeEmulator()
    end)
    if not ok then fail(err) end
end
assert(PCSX.settings.emulator.Debug.Debug and not PCSX.settings.emulator.Dynarec,
    'Use -Debugger for the mapping test')
refs.vsync = PCSX.Events.createEventListener('GPU::Vsync', function()
    frames = frames + 1
    if frames > 120 and not busy then
        busy = true
        PCSX.nextTick(function() fail('No PadRead response within 120 frames') end)
    end
end)
refs.pad = PCSX.addBreakpoint(0x801c7ee4, 'Exec', 4, 'Before Stage 1 processes PadRead result', function()
    if busy then return end
    local raw = tonumber(PCSX.getRegisters().GPR.n.v0)
    if raw == 0 then return end
    busy = true
    PCSX.pauseEmulator()
    if raw ~= expected[index] then
        PCSX.nextTick(function() fail('Unexpected mask or concurrent controller input') end)
        return
    end
    log(string.format('PAD_MAPPING button=%s raw_mask=%08x frame=%d game_processed=false', trials[index], raw, frames))
    PCSX.nextTick(nextTrial)
end)
log('PAD_MAPPING_STARTED version=1')
PCSX.nextTick(nextTrial)
