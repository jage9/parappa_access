-- Offline sound familiarization: emulation remains paused, no rhythm data.
local sounds = Support.extra.dofile('earcons.lua')
earconAuditionSounds = sounds
local order = {'CIRCLE', 'X', 'SQUARE', 'TRIANGLE', 'L1', 'R1'}
PCSX.nextTick(function()
    PCSX.pauseEmulator()
    if not sounds.available then
        local _, err = sounds.play('CIRCLE')
        PCSX.log('AUDITION_FAILED ' .. tostring(err) .. '\n')
        PCSX.quit(2)
        return
    end
    local timer = luv.new_timer()
    earconAuditionTimer = timer
    earconAuditionQuit = PCSX.Events.createEventListener('Quitting', function()
        sounds.stop()
        timer:stop()
        if not timer:is_closing() then timer:close() end
    end)
    local index = 0
    timer:start(1500, 1500, function()
        index = index + 1
        if index > #order then
            timer:stop()
            PCSX.nextTick(function() PCSX.quit(0) end)
            return
        end
        local ok, err = sounds.play(order[index])
        PCSX.log('AUDITION button=' .. order[index] .. ' ok=' .. tostring(ok) .. '\n')
        if not ok then
            timer:stop()
            PCSX.log('AUDITION_FAILED ' .. tostring(err) .. '\n')
            PCSX.nextTick(function() PCSX.quit(2) end)
        end
    end)
end)
