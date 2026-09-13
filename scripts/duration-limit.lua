-- Graceful wall-clock limit, independent of emulation progress.
return function(seconds)
    local timer = luv.new_timer()
    parappaDurationTimer = timer
    parappaDurationQuit = PCSX.Events.createEventListener('Quitting', function()
        timer:stop()
        if not timer:is_closing() then timer:close() end
    end)
    timer:start(seconds * 1000, 0, function()
        PCSX.nextTick(function()
            PCSX.log('DURATION_COMPLETE seconds=' .. seconds)
            PCSX.quit(0)
        end)
    end)
end
