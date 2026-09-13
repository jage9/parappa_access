-- Navigate the default US menu using normal input, then save before play.
-- Run with -Debugger. Never presses a rhythm button during gameplay.
Support.extra.dofile('probe.lua')
Support.extra.dofile('local-control.lua')
local pad = PCSX.SIO0.slots[1].pads[1]
local buttons = PCSX.CONSTS.PAD.BUTTON
local log = function(s) print(s); PCSX.log(s .. '\n') end
if not PCSX.settings.emulator.Debug.Debug or PCSX.settings.emulator.Dynarec then
    log('PREPARE_FAILED launch with -Debugger')
    PCSX.quit(2)
    return
end
local refs, held, frames = {}, {}, 0
stage1Preparation = refs
local function pulse(button)
    pad.setOverride(button)
    held[button] = frames + 6
end
refs.vsync = PCSX.Events.createEventListener('GPU::Vsync', function()
    frames = frames + 1
    for button, release in pairs(held) do
        if frames >= release then pad.clearOverride(button); held[button] = nil end
    end
    if frames == 18000 then
        log('PREPARE_FAILED timeout before Stage 1; inspect log')
        PCSX.nextTick(function() PCSX.quit(2) end)
    end
end)
local function once(address, name, callback)
    refs[#refs + 1] = PCSX.addBreakpoint(address, 'Exec', 4, name, function()
        local ok, err = pcall(callback)
        if not ok then log('PREPARE_FAILED ' .. tostring(err)); PCSX.pauseEmulator() end
        return false
    end)
end
once(0x801c4260, 'Scene 0 initialization', function()
    log('PREPARE scene=0')
    once(0x801c455c, 'Skip opening movie', function()
        local count = 0
        refs.opening = PCSX.Events.createEventListener('GPU::Vsync', function()
            count = count + 1
            if count == 120 then
                log('PREPARE opening=START')
                pulse(buttons.START)
                refs.opening:remove()
            end
        end)
    end)
    once(0x801c4b50, 'Skip scene 0 intro', function() log('PREPARE intro=START'); pulse(buttons.START) end)
    once(0x801c4cd4, 'Confirm default menu selection', function()
        log('PREPARE menu=CROSS')
        pulse(buttons.CROSS)
    end)
end)
once(0x801c7284, 'Scene 1 initialization', function()
    log('PREPARE scene=1')
    once(0x801c77c0, 'Skip Stage 1 introductory movie', function()
        -- Delay until movie input polling is active; release within the movie.
        refs.movie = PCSX.Events.createEventListener('GPU::Vsync', function()
            refs.movieFrames = (refs.movieFrames or 0) + 1
            if refs.movieFrames == 120 then pulse(buttons.START); refs.movie:remove() end
        end)
    end)
    once(0x801c7a60, 'Stage 1 gameplay entry', function()
        for button in pairs(held) do pad.clearOverride(button) end
        held = {}
        PCSX.nextTick(function()
            PCSX.pauseEmulator()
            local file = Support.File.open('../../logs/stage1-gameplay.sstate', 'TRUNCATE')
            assert(not file:failed(), 'Cannot create Stage 1 state')
            file:writeMoveSlice(PCSX.createSaveState())
            file:close()
            log('PREPARE_COMPLETE state=logs/stage1-gameplay.sstate')
            PCSX.quit(0)
        end)
    end)
end)
log('PREPARE_STARTED version=1 timeout_vsync=18000')
