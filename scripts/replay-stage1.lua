-- Replay a local raw save state. Install the probe before resuming execution.
Support.extra.dofile('probe.lua')
Support.extra.dofile('local-control.lua')
local function log(s) print(s); PCSX.log(s .. '\n') end
PCSX.nextTick(function()
    local ok, err = pcall(function()
        PCSX.pauseEmulator()
        local file = Support.File.open('../../logs/stage1-gameplay.sstate')
        assert(not file:failed(), 'Run prepare-stage1.lua first')
        PCSX.loadSaveState(file)
        file:close()
        log('REPLAY_LOADED state=logs/stage1-gameplay.sstate')
        -- Remain paused so an investigator can install targeted probes.
    end)
    if not ok then log('REPLAY_FAILED ' .. tostring(err)); PCSX.quit(2) end
end)
