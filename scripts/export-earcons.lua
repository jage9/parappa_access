-- Export original generated sounds; create logs/earcons before launching.
local sounds = Support.extra.dofile('earcons.lua')
PCSX.nextTick(function()
    PCSX.pauseEmulator()
    local ok, err = pcall(function()
        -- Validate the whole bank before opening any destination file.
        for _, name in ipairs({'CIRCLE', 'X', 'SQUARE', 'TRIANGLE', 'L1', 'R1'}) do
            assert(sounds.wav(name))
        end
        for _, name in ipairs({'CIRCLE', 'X', 'SQUARE', 'TRIANGLE', 'L1', 'R1'}) do
            local path = '../../logs/earcons/' .. string.lower(name) .. '.wav'
            local file = assert(io.open(path, 'wb'))
            local written, failure = file:write(assert(sounds.wav(name)))
            local closed, closeFailure = file:close()
            assert(written, failure)
            assert(closed, closeFailure)
            PCSX.log('EARCON_EXPORTED button=' .. name .. ' path=' .. path .. '\n')
        end
    end)
    if not ok then PCSX.log('EARCON_EXPORT_FAILED ' .. tostring(err) .. '\n') end
    PCSX.quit(ok and 0 or 2)
end)
