-- On-demand score speech; E is free in the installed keyboard mapping.
-- Common integer HUD score, guarded by the active verified overlay profile.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function word(a) return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0]) end
local function short(a) return tonumber(ffi.cast('int16_t*', ram + a - 0x80000000)[0]) end
stageScoreRefs = {}
local refs, held = stageScoreRefs, false
local function publish(kind, stage)
    stage1ResultSequence = (stage1ResultSequence or 0) + 1
    local score = short(0x80091816)
    local file = assert(io.open('../../logs/demo-result.json', 'w'))
    file:write(string.format('{"sequence":%d,"kind":"%s","stage":%d,"score":%d}',
        stage1ResultSequence, kind, stage, score))
    file:close()
    PCSX.log(string.format('STAGE_RESULT kind=%s stage=%d score=%d\n', kind, stage, score))
end
refs.reportScore = function(kind)
    local p = stageScoreContext
    if p and word(p.entry) == 0x27bdffc8 and word(p.loop) == (p.loopWord or 0x27bdffd0) and
        word(0x800943d0) == p.grid and short(0x800916d0) == 0 then
        publish(kind or 'score_live', p.stage)
        return true
    end
    return false
end
refs.keyboard = PCSX.Events.createEventListener('Keyboard', function(event)
    if event.key ~= 101 and event.key ~= 69 then return end
    if event.action == 0 then held = false; return end
    if held then return end
    held = true
    if bit.band(event.mods or 0, 0x0fc0) ~= 0 then return end
    refs.reportScore()
end)
for stage, profile in pairs(Support.extra.dofile('../../scripts/stage-profiles.lua')) do
    local p = profile
    if p.verified and p.result then
        refs[stage] = PCSX.addBreakpoint(p.result, 'Exec', 4, 'Stage result speech context', function()
            if word(p.entry) ~= 0x27bdffc8 or word(p.loop) ~= (p.loopWord or 0x27bdffd0) or
                word(p.result) ~= (p.resultWord or 0x3c128009) or word(0x800943d0) ~= p.grid or short(0x800916d0) ~= 0 then return end
            stageScoreContext = nil
            local value = tonumber(PCSX.getRegisters().GPR.n.v0)
            if p.stage > 1 and (value == 1 or value == 2) then
                publish(value == 1 and 'clear' or 'failure', p.stage)
                if nativeObserver then nativeObserver.setHint(value == 2 and 'X Retry. D Leave.' or '') end
            end
        end)
    end
end
