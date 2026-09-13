-- Opt-in Stage 1 demonstration-only earcon test. No controller automation.
local sounds = nativeCueSounds or Support.extra.dofile('../../scripts/earcons.lua')
if not sounds.available then
    local _, err = sounds.play('CIRCLE')
    PCSX.log('AUDIO_START_FAILED ' .. tostring(sounds.loadError or err) .. '\n')
    PCSX.nextTick(function() PCSX.quit(2) end)
    return
end
for _, name in ipairs({'CIRCLE', 'X', 'SQUARE', 'TRIANGLE', 'L1', 'R1'}) do
    local kind, info = sounds.source(name)
    PCSX.log(string.format('AUDIO_SOURCE button=%s kind=%s duration_ms=%.2f channels=%d panning=%s pan=%.2f\n',
        name, kind, info.durationMs, info.channels, tostring(info.panEnabled), info.pan or 0))
end
local played = 0
local profile = stage1AudioProfile
stage1AudioSounds = sounds -- Keep every async PCM buffer alive through shutdown.
stage1CursorOptions = {
    profile = profile,
    statePath = stage1AudioStatePath,
    frames = stage1AudioFrames or 1800,
    paused = stage1AudioPaused or false,
    loadState = stage1AudioLoadState ~= false,
    keepGameRunning = stage1AudioKeepGameRunning == true,
    note = function(button)
        local started = luv.hrtime()
        local ok, err = sounds.play(button)
        local requestUs = tonumber(luv.hrtime() - started) / 1000
        assert(ok, err or 'Earcon playback failed')
        played = played + 1
        if played <= 2048 then
            PCSX.log(string.format('TEACHER_AUDIO performer=%s button=%s count=%d request_us=%.1f host_ns=%.0f\n',
                profile and profile.teacher:gsub(' ', '_'):upper() or 'MASTER_ONION', button, played, requestUs,
                tonumber(started)))
        end
    end,
    stop = function() sounds.stop() end,
}
Support.extra.dofile('../../scripts/stage1-cursors.lua')
