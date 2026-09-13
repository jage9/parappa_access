-- Fallback PoC: observe the game's current chart row, NOT individual cues.
-- No inputs, memory writes, prediction, or accessibility audio.
local ffi = require('ffi')
local bit = require('bit')
local ram = PCSX.getMemPtr()
local frames, rows = 0, 0
local function log(s) print(s); PCSX.log(s) end
local function u32(address)
    assert(address >= 0x80000000 and address <= 0x801ffffc and address % 4 == 0,
        'Invalid aligned RAM address')
    return tonumber(ffi.cast('uint32_t*', ram + address - 0x80000000)[0])
end
local function u8(address)
    assert(address >= 0x80000000 and address <= 0x801fffff, 'Invalid RAM address')
    return tonumber(ram[address - 0x80000000])
end
local function buttonNames(mask)
    local names = {}
    for _, entry in ipairs({{0x10, 'TRIANGLE'}, {0x20, 'CIRCLE'}, {0x40, 'X'},
        {0x80, 'SQUARE'}, {0x04, 'L1'}, {0x08, 'R1'}}) do
        if bit.band(mask, entry[1]) ~= 0 then names[#names + 1] = entry[2] end
    end
    if bit.band(mask, bit.bnot(0xfc)) ~= 0 then names[#names + 1] = 'UNKNOWN_BITS' end
    return #names > 0 and table.concat(names, '+') or 'NONE'
end
local refs = {}
stage1ChartProbe = refs
log('STAGE1_CHART version=1 kind=chart_rows individual_cues=UNCONFIRMED')
PCSX.nextTick(function()
    local ok, err = pcall(function()
        PCSX.pauseEmulator()
        assert(PCSX.settings.emulator.Debug.Debug, 'Launch with -Debugger')
        assert(not PCSX.settings.emulator.Dynarec, 'Interpreter required; launch with -Debugger')
        local file = Support.File.open('../../logs/stage1-gameplay.sstate')
        assert(not file:failed(), 'Missing state; run prepare-stage1.lua first')
        PCSX.loadSaveState(file)
        file:close()
        assert(u32(0x801c7a60) == 0x27bdffc8 and u32(0x801c81ec) == 0x27bdffd0,
            'Stage 1 code signature mismatch')
        assert(u32(0x8002515c) == 0x90900000 and u32(0x80025180) == 0x94420010,
            'Chart-consumer signature mismatch')
        assert(u32(0x800943c4) == 0x801cd38c and u32(0x800943c8) == 66,
            'Stage 1 chart table mismatch')
        refs.vsync = PCSX.Events.createEventListener('GPU::Vsync', function()
            frames = frames + 1
            if frames == 1800 then
                log(string.format('CHART_CAPTURE_COMPLETE frames=%d rows=%d', frames, rows))
                PCSX.nextTick(function() PCSX.quit(rows > 0 and 0 or 3) end)
            end
        end)
        refs.chart = PCSX.addBreakpoint(0x8002515c, 'Exec', 4, 'Current Stage 1 chart row', function()
            local success, failure = pcall(function()
                local regs = PCSX.getRegisters().GPR.n
                assert(tonumber(regs.s1) == 0x801c3640, 'Unexpected scene-state pointer')
                local pointer = tonumber(regs.a0)
                assert(pointer >= 0x801cd38c and pointer < 0x801cd38c + 66 * 24
                    and (pointer - 0x801cd38c) % 24 == 0, 'Chart row outside Stage 1 table')
                rows = rows + 1
                assert(rows <= 32, 'Unexpected chart consumption rate')
                local mask = u32(pointer + 8)
                log(string.format('CHART_ROW frame=%d tick=%d index=%d pointer=%08x mask=%08x chart_buttons=%s group=%d flags=%04x performer=UNCONFIRMED',
                    frames, u32(0x801c364c), (pointer - 0x801cd38c) / 24,
                    pointer, mask, buttonNames(mask), u8(pointer), bit.band(u32(pointer + 16), 0xffff)))
            end)
            if not success then
                log('CHART_CAPTURE_FAILED ' .. tostring(failure))
                PCSX.nextTick(function() PCSX.quit(2) end)
                return false
            end
        end)
        log('CHART_STATE_LOADED ready=true')
        PCSX.resumeEmulator()
    end)
    if not ok then log('CHART_CAPTURE_FAILED ' .. tostring(err)); PCSX.quit(2) end
end)
