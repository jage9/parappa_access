-- Native card/name UI, verified against the post-clear captures in findings.md.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function word(a) return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0]) end
local function short(a) return tonumber(ffi.cast('int16_t*', ram + a - 0x80000000)[0]) end
local function text(a, limit)
    local result = {}
    for i=0,limit-1 do
        local c = tonumber(ram[a - 0x80000000 + i])
        if c == 0 then break end
        if c >= 32 and c <= 126 then result[#result+1] = string.char(c) end
    end
    return table.concat(result)
end
nativeCardRefs = {}
local refs = nativeCardRefs
local lastMode, lastItem, lastName, variant
local highScoreSeen = false
local punctuation = {[45]='Dash', [33]='Exclamation mark', [64]='At sign',
    [35]='Number sign', [36]='Dollar sign', [38]='Ampersand', [8]='Delete', [10]='End. Cancel',
    [37]='Smiling face', [94]='Laughing face', [61]='Target', [123]='Asterisk',
    [40]='Crescent moon', [41]='Fish skeleton', [95]='Lightning bolt', [43]='Heart',
    [44]='Sun', [46]='Curved symbol', [125]='Boxed X', [91]='Music notes', [93]='Star'}
local function letter(code)
    if punctuation[code] then return punctuation[code] end
    if code >= 48 and code <= 57 or code >= 65 and code <= 90 then return string.char(code) end
    -- The game's symbol font differs from ASCII; avoid calling a pictogram punctuation.
    return 'Symbol ' .. code
end
local function displayName(name)
    if name:match('^[A-Z0-9]*$') then return name end
    local labels = {}
    for i=1,#name do labels[#labels+1] = letter(name:byte(i)) end
    return table.concat(labels, ' ')
end

-- The 2026-09-11 retail capture shows a six-row table with three crown
-- columns. The formatter's input is six 0x40-byte groups at 0x8009421c;
-- each group has four 0x10-byte records, while only the first three are
-- rendered. A record's score is a signed 32-bit value at +0x0c and its
-- visible name is the first three bytes of the six-byte stored name.
local highScoreRecords = 0x8009421c
local highScoreTable = 0x80049278
local function signedWord(a)
    return tonumber(ffi.cast('int32_t*', ram + a - 0x80000000)[0])
end
local rankNames = {'Gold', 'Silver', 'Bronze'}
local function highScoreText()
    local rows = short(highScoreTable + 0x0c)
    local columns = short(highScoreTable + 0x0e)
    if rows ~= 6 or columns ~= 3 then return nil end
    local parts = {'High scores.'}
    for row=0,rows-1 do
        local entries = {}
        for rank=0,columns-1 do
            local record = highScoreRecords + row * 0x40 + rank * 0x10
            local score = signedWord(record + 0x0c)
            local name = text(record, 3)
            if score > 0 then
                entries[#entries+1] = rankNames[rank+1] .. ' ' .. tostring(score) ..
                    (name ~= '' and (' ' .. displayName(name)) or '')
            else
                entries[#entries+1] = rankNames[rank+1] .. ' empty'
            end
        end
        parts[#parts+1] = 'Stage ' .. (row + 1) .. '. ' .. table.concat(entries, '. ') .. '.'
    end
    parts[#parts+1] = 'Exit.'
    return table.concat(parts, ' ')
end
refs.highscoreText = highScoreText
refs.enter = PCSX.addBreakpoint(0x800191e4, 'Exec', 4, 'Native card entry', function()
    if word(0x800191e4) ~= 0x27bdffd8 then return end
    variant = tonumber(PCSX.getRegisters().GPR.n.a1)
    highScoreSeen = false
    lastMode, lastItem, lastName = nil, nil, nil
end)
refs.save = PCSX.addBreakpoint(0x80019148, 'Exec', 4, 'Native save entry', function()
    if word(0x80019148) ~= 0x27bdffe0 then return end
    variant = nil
    highScoreSeen = false
    lastMode, lastItem, lastName = nil, nil, nil
end)

-- High scores are built by 0x80019414 and entered through the common modal
-- with id 6. This hook runs after the table has been formatted, before the
-- modal consumes input. It emits one summary so Prism does not interrupt
-- itself once per cell.
refs.highscore = PCSX.addBreakpoint(0x80026b94, 'Exec', 4, 'Native high-score table', function()
    if highScoreSeen or variant ~= 3 or not nativeObserver then return end
    local r = PCSX.getRegisters().GPR.n
    if word(0x80026b94) ~= 0x27bdffc8 or tonumber(r.a0) ~= 6 or
        tonumber(r.a1) ~= highScoreTable then return end
    local summary = highScoreText()
    if not summary then return end
    highScoreSeen = true
    nativeObserver.announce(summary, 'X Exit.')
end)
refs.mode = PCSX.addBreakpoint(0x800180d8, 'Exec', 4, 'Native card selection', function()
    if word(0x800180d8) ~= 0x27bdffe0 or not nativeObserver then return end
    local r = PCSX.getRegisters().GPR.n
    local mode, state = tonumber(r.a0), tonumber(r.a2)
    local entering = mode ~= lastMode
    if entering then
        lastMode, lastItem, lastName = mode, nil, nil
        nativeObserver.setHint('')
    end
    if mode == 2 then
        if entering then nativeObserver.announce('Save? Yes. No.', 'X Yes. D No.') end
    elseif mode == 17 and variant == 3 and state == 0x8007cc50 then
        if entering then nativeObserver.announce('Please wait a minute.') end
    elseif mode == 10 and state == 0x80049244 then
        local cursor, count = short(state + 0x16), short(state + 0x14)
        if word(state + 0xc) ~= 0x800490e8 or count ~= 57 or cursor < 0 or cursor >= count then return end
        local code = tonumber(ram[0x490e8 + cursor])
        local name = text(state + 0x1c, 6)
        local hint = code == 10 and 'X Save. D Cancel.' or 'Arrows Select. X Type. S Delete. Select End to finish.'
        if cursor ~= lastItem then
            nativeObserver.announce((lastItem == nil and 'Name entry. Enter your name here. ' or '') .. letter(code) .. '.', hint)
        elseif name ~= lastName then
            nativeObserver.announce('Name ' .. (name == '' and 'blank' or displayName(name)) .. '.', hint)
        end
        lastItem, lastName = cursor, name
    elseif (mode == 11 or mode == 12 and variant == 1 or mode == 13 and variant == 2) and state == 0x80048e50 then
        local cursor = short(state + 0x14)
        if short(state + 0x10) ~= 16 or cursor < 0 or cursor > 15 then return end
        if cursor == lastItem then return end
        local name = cursor < 15 and text(0x8007a590 + cursor * 0x6c + 0x5c, 6) or ''
        local item = cursor == 15 and 'Exit' or (name == '' and 'Empty slot ' .. (cursor + 1) or displayName(name))
        local heading = mode == 11 and 'Save. ' or (mode == 13 and 'Replay. ' or 'Load. ')
        local action = cursor == 15 and 'Exit' or (mode == 11 and 'Save' or (mode == 13 and 'Replay' or 'Load'))
        nativeObserver.announce((lastItem == nil and heading or '') .. item .. '.', 'Arrows Select. X ' .. action .. '.')
        lastItem = cursor
    end
end)
for _, address in ipairs({0x800191dc, 0x8001927c}) do
    refs[address] = PCSX.addBreakpoint(address, 'Exec', 4, 'Native card return', function()
        if word(address) ~= 0x03e00008 then return end
        highScoreSeen = false
        lastMode, lastItem, lastName = nil, nil, nil
        if nativeObserver then nativeObserver.setHint('') end
    end)
end
