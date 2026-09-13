-- At most one new entry and clear checkpoint per stage per session; never replace states.
-- No input, cue playback, or automatic loading. Candidate stages remain silent.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function word(address)
    return tonumber(ffi.cast('uint32_t*', ram + address - 0x80000000)[0])
end
progressCheckpointRefs = {}
local refs = progressCheckpointRefs
local function checkpoint(label)
    PCSX.nextTick(function()
        local ok, err = pcall(function()
            local stem = '../../logs/progress-' .. label .. '-' .. os.date('!%Y%m%dT%H%M%SZ')
            local path
            for index = 1, 100 do
                local candidate = stem .. '-' .. index .. '.sstate'
                local existing = io.open(candidate, 'rb')
                if existing then existing:close() else path = candidate; break end
            end
            assert(path, 'No unused checkpoint filename')
            local state = PCSX.createSaveState()
            local file = Support.File.open(path, 'TRUNCATE')
            assert(not file:failed(), 'Cannot create checkpoint')
            file:writeMoveSlice(state)
            file:close()
            PCSX.log('PROGRESS_CHECKPOINT kind=' .. label .. ' path=' .. path .. '\n')
        end)
        if not ok then PCSX.log('PROGRESS_CHECKPOINT_ERROR ' .. tostring(err) .. '\n') end
    end)
end
for stage, profile in pairs(Support.extra.dofile('../../scripts/stage-profiles.lua')) do
    local p = profile
    refs['clear' .. stage] = PCSX.addBreakpoint(p.result, 'Exec', 4, 'Research stage-clear checkpoint', function()
        if word(p.entry) ~= 0x27bdffc8 or word(p.loop) ~= (p.loopWord or 0x27bdffd0) or
            word(p.result) ~= (p.resultWord or 0x3c128009) or word(0x800943d0) ~= p.grid then return end
        if tonumber(PCSX.getRegisters().GPR.n.v0) ~= 1 then return end
        checkpoint('stage' .. p.stage .. '-clear')
        return false
    end)
    if stage > 1 then
        refs['entry' .. stage] = PCSX.addBreakpoint(p.entry, 'Exec', 4, 'Research stage-entry checkpoint', function()
            if word(p.entry) ~= 0x27bdffc8 or word(p.loop) ~= (p.loopWord or 0x27bdffd0) or
                word(p.primary[1]) ~= 0x80430000 or word(p.response[1]) ~= 0x80430000 then return end
            checkpoint('stage' .. p.stage .. '-entry')
            return false
        end)
    end
end
