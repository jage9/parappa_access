-- Native Practice text and feedback; control instructions remain H-only.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function word(a) return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0]) end
local refs = {}
nativePracticeRefs = refs
-- Cache file buffers at native startup, before the tutorial or a song starts.
nativeCueSounds = nativeCueSounds or Support.extra.dofile('../../scripts/earcons.lua')
refs.sounds = nativeCueSounds
local audioCount = 0
local function stopAudio()
    if refs.sounds.available then refs.sounds.stop() end
end
local active, lastPhase = false, nil
local feedback = {
    [0] = 'Exactly!', [1] = 'You are too quick.', [2] = 'You are too slow.',
    [4] = 'Next one is ...', [5] = 'How about this one?', [6] = 'The last one is ...',
    [7] = "OK, are you ready? Let's go rappin!", [8] = 'You wanna try again?',
}
refs.draw = PCSX.addBreakpoint(0x80023618, 'Exec', 4, 'Native Practice screen', function()
    local r = PCSX.getRegisters().GPR.n
    if tonumber(r.a0) ~= 0x801c3640 or tonumber(r.ra) ~= 0x8001e998 or
        word(0x80023618) ~= 0x27bdffc0 or word(0x8002776c) ~= 0x27bdff58 or
        bit.band(word(0x800916d0), 0xffff) ~= 0 then return end
    local phase = bit.band(word(0x801c3640), 0x400000) == 0 and -1 or word(0x801c365c)
    local hint = phase == 8 and 'Push the Circle button. D Try again. X Exit.' or
        'Look at the bar, press the Triangle button. S Triangle. X Exit.'
    if not active then
        active = true
        if refs.sounds.available then
            local ok, err = refs.sounds.prime()
            if not ok then PCSX.log('PRACTICE_AUDIO_PREPARE_FAILED '..tostring(err)..'\n') end
        end
        nativeObserver.announce('Practice.', hint)
    end
    if phase ~= lastPhase then
        if feedback[phase] then
            -- Each newly displayed result is an event, including repeated Exactly.
            nativeObserver.announce(feedback[phase], hint, true)
        else
            nativeObserver.setHint(phase == -1 and hint or '')
        end
    end
    lastPhase = phase
end)
refs.exit = PCSX.addBreakpoint(0x80027f70, 'Exec', 4, 'Native Practice exit', function()
    if not active or word(0x80027f70) ~= 0x0c005564 or
        tonumber(PCSX.getRegisters().GPR.n.s1) ~= 0x801c3640 then return end
    stopAudio()
    active, lastPhase = false, nil
    nativeObserver.setHint('')
end)
-- This call is the existing teacher's sound event, not the moving bar cursor.
-- Practice uses only Triangle; all four chart rows and the input mask agree.
refs.teacher = PCSX.addBreakpoint(0x80027bb4, 'Exec', 4, 'Practice teacher sound', function()
    if not active or not refs.sounds.available then return end
    local r = PCSX.getRegisters().GPR.n
    if word(0x80027bb4) ~= 0x0c009bbe or word(0x8002776c) ~= 0x27bdff58 or
        tonumber(r.s1) ~= 0x801c3640 or tonumber(r.s3) ~= 1 or
        bit.band(word(0x800916d0), 0xffff) ~= 0 then return end
    local sp = tonumber(r.sp)
    if sp < 0x80000000 or sp > 0x801fffbf or tonumber(r.s2) ~= word(sp + 0x38) then return end
    local ptr = word(0x801c36d4)
    local pattern = (ptr - 0x800554dc) / 44
    if pattern < 0 or pattern > 3 or pattern ~= math.floor(pattern) then return end
    for i = 0, 16 do
        local expected = i == 2 + pattern * 4 and 1 or (i == 16 and 255 or 0)
        if tonumber(ram[ptr - 0x80000000 + i]) ~= expected then return end
    end
    local ok, err = refs.sounds.play('TRIANGLE')
    if not ok then PCSX.log('PRACTICE_AUDIO_FAILED '..tostring(err)..'\n');return end
    audioCount = audioCount + 1
    if audioCount <= 512 then
        PCSX.log(string.format('PRACTICE_TEACHER_AUDIO button=TRIANGLE pattern=%d tick=%d count=%d\n',pattern,tonumber(r.s2),audioCount))
    end
end)
refs.pause = PCSX.Events.createEventListener('ExecutionFlow::Pause', function()
    if active then stopAudio() end
end)
refs.lifecycle = {}
for _, event in ipairs({'ExecutionFlow::Reset', 'ExecutionFlow::SaveStateLoaded', 'IsoMounted', 'Quitting'}) do
    refs.lifecycle[#refs.lifecycle+1] = PCSX.Events.createEventListener(event, function()
        if active then stopAudio() end
        active, lastPhase = false, nil
    end)
end
return refs
