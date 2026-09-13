-- Minimal startup proof; no inputs, patches, or accessibility cues.
local function log(text)
    print(text)
    PCSX.log(text .. '\n')
end
log('PARAPPA_PROBE version=1 lua=' .. _VERSION .. ' cycles=' .. tostring(PCSX.getCPUCycles()))
local frames = 0
parappaProbeListener = PCSX.Events.createEventListener('GPU::Vsync', function()
    frames = frames + 1
    if frames % 300 == 0 then
        log(string.format('PARAPPA_PROBE vsync=%d pc=%08x cycles=%s',
            frames, tonumber(PCSX.getRegisters().pc), tostring(PCSX.getCPUCycles())))
    end
end)
