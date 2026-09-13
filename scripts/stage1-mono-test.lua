-- Bounded listening test for Redux's mono-XA right-channel problem.
-- Restore the existing mixer preference before the normal automatic exit.
local previous = PCSX.settings.spu.Mono
local function restore()
    PCSX.settings.spu.Mono = previous
    PCSX.log('MONO_TEST_RESTORED value=' .. tostring(previous) .. '\n')
end
local ok, err = pcall(function()
    PCSX.settings.spu.Mono = true
    PCSX.log('MONO_TEST_STARTED previous=' .. tostring(previous) .. '\n')
    Support.extra.dofile('../../scripts/stage1-audio.lua')
    assert(stage1CursorOptions, 'Audio initialization failed')
    local stop = stage1CursorOptions.stop
    stage1CursorOptions.stop = function()
        restore()
        if stop then stop() end
    end
end)
if not ok then
    restore()
    PCSX.log('MONO_TEST_FAILED ' .. tostring(err) .. '\n')
    PCSX.nextTick(function() PCSX.quit(2) end)
end
