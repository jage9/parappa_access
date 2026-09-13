-- Verified US title selection and live Stage 1 entry. No input automation.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function u32(a)
    assert(a >= 0x80000000 and a <= 0x801ffffc, 'Native address outside RAM')
    return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0])
end
local refs = {}
nativeObserver = refs
local sequence, lastSelection = 0, nil
local lastScreen
local mainMenuKey
local mainMenuSuppressed = false
local stageMenuKey
local currentHint = ''
-- Transcribed from the pinned game's title artwork; spoken once on entry.
local titleDescription = 'PaRappa beneath a colorful logo. PaRappa the Rapper, trademark. '
    .. 'The Hip Hop Hero. '
    .. 'Copyright 1997 Sony Computer Entertainment Inc. Copyright Rodney A. Greenblat slash Interlink. '
    .. 'Trademark of Sony Computer Entertainment America Inc. '
local function publish(text, hint)
    sequence = sequence + 1
    local f = assert(io.open('../../logs/native-event.json', 'w'))
    local function escape(value)
        return value:gsub('[%z\1-\31\\"]', function(c)
            if c == '\\' then return '\\\\' end
            if c == '"' then return '\\"' end
            return string.format('\\u%04x', c:byte())
        end)
    end
    f:write(string.format('{"sequence":%d,"text":"%s","hint":"%s"}', sequence, escape(text), escape(hint or '')))
    f:close()
    PCSX.log('NATIVE_EVENT ' .. text .. '\n')
end
local function announce(text, hint, force)
    currentHint = hint or ''
    local key = text .. '\n' .. currentHint
    if key == lastScreen and not force then return end
    lastScreen = key
    publish(text, '')
end
refs.announce = announce
refs.setHint = function(hint) currentHint = hint or '' end
refs.repeatHint = function()
    if currentHint ~= '' then publish('', currentHint) end
end
local hintHeld = false
refs.keyboard = PCSX.Events.createEventListener('Keyboard', function(event)
    if event.key ~= 104 and event.key ~= 72 then return end -- SDL H/h keycode.
    if event.action == 0 then hintHeld = false; return end
    if hintHeld then return end
    hintHeld = true
    if bit.band(event.mods or 0, 0x0fc0) ~= 0 then return end -- Ctrl/Alt/GUI shortcuts.
    refs.repeatHint()
end)
local function mainMenuSelection()
    local selected = bit.band(u32(0x80054504), 0xffff)
    local difficulty = bit.band(u32(0x80054510), 0xffff)
    if selected > 4 or difficulty > 1 then return end
    local key = tostring(selected) .. ':' .. tostring(difficulty)
    if key == mainMenuKey then return end
    local entering = mainMenuKey == nil
    local changingDifficulty = selected == 2 and mainMenuKey and mainMenuKey:match('^2:')
    mainMenuKey = key
    stageMenuKey = nil
    local labels = {
        'Language.', 'High scores.',
        (changingDifficulty and '' or 'Difficulty. ') .. (difficulty == 0 and 'Normal.' or 'Easy.'),
        'Stage.', 'Exit.',
    }
    local hints = {'X Open.', 'X Open.', 'X Normal. D Easy.',
                   'X Stage. Z Practice. D Replay. S Load.', 'X Exit.'}
    announce((entering and 'Main menu. ' or '') .. labels[selected + 1], hints[selected + 1])
end
refs.mainMenu = PCSX.addBreakpoint(0x80026720, 'Exec', 4, 'Main menu selection', function()
    if mainMenuSuppressed then return end
    local r = PCSX.getRegisters().GPR.n
    if tonumber(r.a0) ~= 0x80054550 or u32(0x80054560) ~= 0x800544f8 or
        u32(0x80026720) ~= 0x27bdffe8 or bit.band(u32(0x80054506), 0xffff) ~= 5 then return end
    mainMenuSelection()
end)
refs.mainMenuEntry = PCSX.addBreakpoint(0x80026b94, 'Exec', 4, 'Native main menu entry', function()
    if u32(0x80026b94) == 0x27bdffc8 and tonumber(PCSX.getRegisters().GPR.n.a0) == 3 then
        mainMenuKey, mainMenuSuppressed = nil, false
    end
end)
refs.mainAction = PCSX.addBreakpoint(0x80026704, 'Exec', 4, 'Main menu action', function()
    local r = PCSX.getRegisters().GPR.n
    if tonumber(r.s0) ~= 0x800544f8 or u32(0x80026704) ~= 0x8fbf0024 then return end
    local action = tonumber(r.v0)
    local labels = {[1] = 'High scores', [2] = 'Replay selection', [3] = 'Practice selection',
                    [4] = 'Stage selection', [6] = 'Load game', [8] = 'Language'}
    if action == 7 or labels[action] then mainMenuSuppressed = true end
    if action == 7 then
        mainMenuKey = nil
        currentHint = ''
    elseif action == 1 or action == 2 or action == 3 or action == 4 or action == 6 or action == 8 then
        mainMenuKey, stageMenuKey = nil, nil
        currentHint = '' -- Supported selectors announce themselves when drawn.
    elseif labels[action] then
        mainMenuKey = nil
        announce(labels[action] .. '.', 'This submenu is not yet fully read.')
    end
end)
-- Common modal 2, verified Stage Select descriptor and cursor.
refs.stageMenuInit = PCSX.addBreakpoint(0x800267f8, 'Exec', 4, 'Stage menu entry', function()
    if tonumber(PCSX.getRegisters().GPR.n.a0) ~= 0x8005453c or
        u32(0x800267f8) ~= 0x8c860010 or u32(0x8005454c) ~= 0x80087b78 then return end
    stageMenuKey = nil
    mainMenuKey = nil
    currentHint = ''
end)
refs.stageMenu = PCSX.addBreakpoint(0x80026170, 'Exec', 4, 'Stage menu selection', function()
    if tonumber(PCSX.getRegisters().GPR.n.a0) ~= 0x8005453c or
        u32(0x80026170) ~= 0x27bdffe8 or u32(0x80026178) ~= 0x8c840010 or
        u32(0x8005454c) ~= 0x80087b78 then return end
    local state = 0x80087b78
    local selected = bit.band(u32(state + 8), 0xffff)
    if selected < 1 or selected > 8 or bit.band(u32(state + 10), 0xffff) ~= 8 then return end
    if selected == stageMenuKey then return end
    local entering = stageMenuKey == nil
    stageMenuKey = selected
    local label = selected == 8 and 'Exit.' or
        (selected == 7 and 'Selection 7.' or 'Stage ' .. selected .. '.')
    announce(entering and 'Stage select.' or label,
        selected == 8 and 'Arrows Select. X Exit.' or 'Arrows Select. X Play.')
end)
local screenHooks = {}
local function screen(address, word, following, caller, text, hint)
    local hook = PCSX.addBreakpoint(address, 'Exec', 4, 'Native screen', function()
        if u32(address) ~= word or u32(address + 4) ~= following then return end
        if caller and tonumber(PCSX.getRegisters().GPR.n.ra) ~= caller then return end
        if address == 0x801c77c0 and (u32(0x801c7a60) ~= 0x27bdffc8 or
            bit.band(u32(0x800916d0), 0xffff) ~= 0 or
            tonumber(PCSX.getRegisters().GPR.n.a2) ~= 0) then return end
        announce(text, hint)
    end)
    screenHooks[#screenHooks + 1] = hook
end
-- After each credit fades in, before its display wait. Pinned US boot code.
screen(0x80016bfc, 0x34040096, 0x3405003c, nil,
    'Sony Computer Entertainment America Presents.')
screen(0x80016c44, 0x34040096, 0x3405003c, nil,
    'Masaya Matsuura Presents.')
screen(0x801c455c, 0x27bdffd0, 0xafb50024, 0x801c4e54,
    'Opening scene.', 'Enter Skip.')
screen(0x801c4b50, 0x0c00d544, 0x34040001, 0x801c49e0,
    'Title animation.', 'Enter Skip.')
screen(0x801c77c0, 0x27bdffd0, 0xafb50024, nil,
    'Stage 1. PaRappa portrait, pink lettering, Onion border. '
        .. 'Card and subtitle: I need to become a hero!', 'Enter Skip.')
refs.title = PCSX.addBreakpoint(0x801c4d24, 'Exec', 4, 'Native title selection', function()
    -- Scene overlays reuse addresses. Match the observed title draw call.
    if u32(0x801c4d24) ~= 0x0c071615 or u32(0x801c4d20) ~= 0x8fa50010 then return end
    local r = PCSX.getRegisters().GPR.n
    if tonumber(r.s1) ~= 0x801c3640 then return end
    -- Read the stack word: a1 still contains the old value in the load delay slot.
    local selected = u32(tonumber(r.sp) + 0x10)
    if selected ~= 0 and selected ~= 1 then return end
    if selected ~= lastSelection then
        local entering = lastSelection == nil
        local text = selected == 0 and 'Start.' or 'Menu.'
        announce((entering and titleDescription or '') .. text,
            'Left and Right Select. X Confirm.')
        lastSelection = selected
    end
end)
refs.titleExit = PCSX.addBreakpoint(0x801c4e8c, 'Exec', 4, 'Native title exit', function()
    if u32(0x801c4e84) ~= 0x0c071225 or u32(0x801c4e90) ~= 0x00408021 then return end
    lastSelection = nil
    if tonumber(PCSX.getRegisters().GPR.n.v0) == 1 then
        mainMenuKey = nil
        currentHint = '' -- The menu name is spoken when its first item is drawn.
    elseif tonumber(PCSX.getRegisters().GPR.n.v0) == 2 then
        announce('Loading Stage 1.')
    end
end)
refs.entry = PCSX.addBreakpoint(0x801c7a60, 'Exec', 4, 'Native Stage 1 entry', function()
    if u32(0x801c7a60) ~= 0x27bdffc8 or u32(0x801c81ec) ~= 0x27bdffd0
        or bit.band(u32(0x800916d0), 0xffff) ~= 0 then return end -- Exclude attract mode.
    -- The gameplay initializer installs the grid before the next-tick attach
    -- validates it; it need not be populated at the function entry itself.
    lastSelection = nil
    if stage1CursorProbe and stage1CursorProbe.isActive() then return end
    -- Overlay addresses are reused. Title probes must not stay active in
    -- unrelated Stage 1 code, even when their signature guards reject it.
    refs.title:disable()
    refs.titleExit:disable()
    refs.entry:disable()
    -- Common menu code can run while the Stage 1 overlay remains loaded.
    -- Its descriptor guards are safe to leave active during gameplay.
    mainMenuKey = nil
    for _, hook in ipairs(screenHooks) do hook:disable() end
    announce('Stage 1. Master Onion.')
    nativeStage1Attach()
    PCSX.log('NATIVE_STAGE1_ATTACH\n')
end)
refs.stage1Detached = function()
    lastSelection = nil
    refs.title:enable()
    refs.titleExit:enable()
    refs.entry:enable()
    refs.mainMenu:enable()
    refs.mainAction:enable()
    mainMenuKey = nil
    for _, hook in ipairs(screenHooks) do hook:enable() end
end
PCSX.log('NATIVE_READY original_boot=true automated_input=false\n')
