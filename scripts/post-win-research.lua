-- Bounded, read-only common save/load UI research; no speech or controller input.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function u32(a) return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0]) end
local function s16(a) return tonumber(ffi.cast('int16_t*', ram + a - 0x80000000)[0]) end
local function hex(a, length)
    local bytes = {}
    for i = 0, length - 1 do bytes[#bytes + 1] = string.format('%02x', tonumber(ram[a - 0x80000000 + i])) end
    return table.concat(bytes)
end
postWinResearchRefs = {}
local refs = postWinResearchRefs
local entries, previous = 0, {}
local function observe(key, address, signature, callback)
    refs[key] = PCSX.addBreakpoint(address, 'Exec', 4, 'Post-win research ' .. key, function()
        if entries >= 256 then return false end
        if u32(address) ~= signature then return end
        local ok, err = pcall(function()
            local details = callback(PCSX.getRegisters().GPR.n)
            if details == previous[key] then return end
            previous[key] = details
            entries = entries + 1
            PCSX.log('POST_WIN_RESEARCH kind=' .. key .. ' ' .. details .. '\n')
        end)
        if not ok then
            PCSX.log('POST_WIN_RESEARCH_ERROR ' .. key .. ' ' .. tostring(err) .. '\n')
            return false
        end
    end)
end
local function selection()
    local count, cursor = s16(0x80048e60), s16(0x80048e64)
    local selected = ''
    -- Runtime count is 16: fifteen possible card slots plus Exit at index 15.
    if count > 0 and count <= 16 and cursor >= 0 and cursor < math.min(count, 15) then
        selected = ' record_name_hex=' .. hex(0x8007a590 + cursor * 0x6c + 0x5c, 16)
    end
    return string.format('count_raw=%d cursor_raw=%d name_hex=%s edit_hex=%s',
        count, cursor, hex(0x8007cbe8, 32), hex(0x80049258, 20)) .. selected
end
for _, spec in ipairs({{'save_enter', 0x80019148, 0x27bdffe0}, {'load_enter', 0x800191e4, 0x27bdffd8}}) do
    observe(spec[1], spec[2], spec[3], function(r)
        previous = {}
        return string.format('caller=%08x a0=%08x', tonumber(r.ra), tonumber(r.a0))
    end)
end
observe('save_input', 0x800185d0, 0x27bdff90, function(r)
    return string.format('mode_raw=%d ', tonumber(r.a1)) .. selection()
end)
observe('load_input', 0x80018e10, 0x27bdffe8, function(r)
    return string.format('mode_raw=%d ', tonumber(r.a1)) .. selection()
end)
observe('selector', 0x800181d0, 0x27bdffd8, function() return selection() end)
observe('screen_mode', 0x800180d8, 0x27bdffe0, function(r)
    return string.format('mode_raw=%d a1=%08x a2=%08x ', tonumber(r.a0), tonumber(r.a1), tonumber(r.a2)) .. selection()
end)
