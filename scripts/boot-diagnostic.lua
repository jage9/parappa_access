Support.extra.dofile('probe.lua')
Support.extra.dofile('local-control.lua')
local function log(s) print(s); PCSX.log(s .. '\n') end
bootBreakpoints = {}
for _, item in ipairs({
    {0x800154f4, 'App_Init'}, {0x8001a1cc, 'CD_Init'},
    {0x80026e4c, 'Rap_Init'}, {0x80027fac, 'VText_Init'},
    {0x80015d18, 'App_Loop'}, {0x80016b84, 'Menu_Opening'},
    {0x80016ab4, 'Menu_CheckDebug'}, {0x801c4260, 'Scene0_Init'}, {0x801c4dc4, 'Scene0_Loop'},
    {0x801c7284, 'Scene1_Init'}, {0x801c81ec, 'Scene1_Loop'}
}) do
    bootBreakpoints[#bootBreakpoints + 1] = PCSX.addBreakpoint(item[1], 'Exec', 4, item[2], function()
        log(string.format('BOOT_MILESTONE candidate=%s pc=%08x ra=%08x', item[2], item[1], tonumber(PCSX.getRegisters().GPR.n.ra)))
        return false
    end)
end
local f = 0
bootDiagnosticListener = PCSX.Events.createEventListener('GPU::Vsync', function()
    f = f + 1
    if f % 600 == 0 then
        local r = PCSX.getRegisters()
        log(string.format('BOOT_DIAGNOSTIC frame=%d pc=%08x ra=%08x sp=%08x', f, tonumber(r.pc), tonumber(r.GPR.n.ra), tonumber(r.GPR.n.sp)))
    end
end)
