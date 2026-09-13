-- Human-selected checkpoint, paused before play; no controller automation.
local paths = {
    'stage1-gameplay.sstate',
    'progress-stage2-entry-20260911T070204Z-1.sstate',
    'progress-stage3-entry-20260911T074303Z-1.sstate',
    'progress-stage4-entry-20260911T075428Z-1.sstate',
    'progress-stage5-entry-20260911T080745Z-1.sstate',
    'progress-stage6-entry-20260911T092343Z-1.sstate',
}
local stage = checkpointStage
if stage == nil then
    local f = io.open('../../logs/checkpoint-stage.txt', 'r')
    if f then stage = tonumber(f:read('*a')); f:close() end
end
if not (stage and stage == math.floor(stage) and paths[stage]) then
    PCSX.log('CHECKPOINT_START_FAILED choose a stage from 1 to 6 in the launcher\n')
    PCSX.nextTick(function() PCSX.quit(2) end)
    return
end
local profile = Support.extra.dofile('../../scripts/stage-profiles.lua')[stage]
assert(profile.verified, 'Checkpoint profile is not verified')
Support.extra.dofile('../../scripts/native-play.lua')
checkpointPlayRefs = {stage=stage, path=paths[stage]}
local refs = checkpointPlayRefs
local pending = false
local originalDraw = DrawImguiFrame
local function fail(err)
    PCSX.log('CHECKPOINT_START_FAILED '..tostring(err)..'\n')
    PCSX.quit(2)
end
-- nextTick callbacks scheduled from inside another nextTick are discarded by
-- this Redux build. Attach from a subsequent UI iteration while still paused.
DrawImguiFrame = function()
    if pending then
        pending = false
        local ok, err = pcall(function()
            stage1AudioPaused = true
            nativeStage1Attach(profile)
            stage1AudioPaused = false
            local ready = assert(stage1CursorOptions).ready
            stage1CursorOptions.ready = function()
                if ready then ready() end
                nativeObserver.setHint('')
                refs.ready = true
                PCSX.log('CHECKPOINT_READY stage='..stage..' paused=true\n')
            end
        end)
        if not ok then fail(err) end
    end
    if originalDraw then originalDraw() end
end
PCSX.nextTick(function()
    local ok, err = pcall(function()
        PCSX.pauseEmulator()
        local f = Support.File.open('../../logs/'..paths[stage])
        assert(not f:failed(), 'Checkpoint file unavailable: '..paths[stage])
        PCSX.loadSaveState(f); f:close()
        local ffi = require('ffi'); local ram = PCSX.getMemPtr()
        local function word(a) return tonumber(ffi.cast('uint32_t*', ram+a-0x80000000)[0]) end
        assert(word(profile.entry)==0x27bdffc8 and word(profile.loop)==(profile.loopWord or 0x27bdffd0) and
            word(0x800943d0)==profile.grid and word(0x800943d4)==profile.count, 'Checkpoint profile mismatch')
        pending = true
        PCSX.log('CHECKPOINT_LOADED stage='..stage..' file='..paths[stage]..'\n')
    end)
    if not ok then fail(err) end
end)
