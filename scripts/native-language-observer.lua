-- Verified native Language modal; observations only, with shared H-only hints.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function word(a) return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0]) end
local function short(a) return tonumber(ffi.cast('int16_t*', ram + a - 0x80000000)[0]) end
local descriptor, state = 0x800545a0, 0x8005451c
local languages = {'English', 'Deutsch', 'Français', 'Italiano', 'Español'}
local refs = {}
nativeLanguageRefs = refs
local active, lastGroup, lastValue = false, nil, nil
local function context()
    return word(descriptor) == 0x800268e4 and word(descriptor + 4) == 0x80026910 and
        word(descriptor + 8) == 0x80026b54 and word(descriptor + 0x10) == state and
        bit.band(word(0x800916d0), 0xffff) == 0
end
refs.modal = PCSX.addBreakpoint(0x80026b94, 'Exec', 4, 'Native Language entry', function()
    if word(0x80026b94) ~= 0x27bdffc8 then return end
    local r = PCSX.getRegisters().GPR.n
    local entering = tonumber(r.a0) == 17 and tonumber(r.a1) == 0x800916d0 and
        tonumber(r.ra) == 0x800159bc and context()
    if active and not entering then nativeObserver.setHint('') end
    active, lastGroup, lastValue = entering, nil, nil
end)
refs.draw = PCSX.addBreakpoint(0x80026b54, 'Exec', 4, 'Native Language selection', function()
    if not active or not context() or tonumber(PCSX.getRegisters().GPR.n.a0) ~= descriptor or
        word(0x80026b54) ~= 0x27bdffe8 or word(0x80026b58) ~= 0xafbf0010 then return end
    local group, subtitle, language, exit = short(state + 8), short(state + 12), short(state + 16), short(state + 20)
    if short(state + 10) ~= 3 or short(state + 14) ~= 2 or short(state + 18) ~= 5 or
        short(state + 22) ~= 1 or group < 0 or group > 2 or subtitle < 0 or subtitle > 1 or
        language < 0 or language > 4 or exit ~= 0 then return end
    local value = group == 0 and (subtitle == 0 and 'On.' or 'Off.') or
        (group == 1 and languages[language + 1] .. '.' or 'Exit.')
    if group == lastGroup and value == lastValue then return end
    local label = group == 0 and group ~= lastGroup and ('Subtitles. ' .. value) or value
    local hint = group == 0 and 'X On. D Off. Up/Down Section.' or
        (group == 1 and 'Left/Right Select. Up/Down Section.' or 'X Exit. Up/Down Section.')
    nativeObserver.announce((lastGroup == nil and 'Language. ' or '') .. label, hint)
    lastGroup, lastValue = group, value
end)
return refs
