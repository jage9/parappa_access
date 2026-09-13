-- Local developer control only. Commands are Lua files authored in logs/ by
-- the operator; no network service and no game data is modified.
local command = '../../logs/control.lua'
local log = function(s) print(s); PCSX.log(s .. '\n') end
function DrawImguiFrame()
    local f = io.open(command, 'r')
    if not f then return end
    local code = f:read('*a'); f:close()
    os.remove(command)
    local fn, err = loadstring(code, '@local-control')
    if fn then
        local ok, result = pcall(fn)
        log('LOCAL_CONTROL ok=' .. tostring(ok) .. ' result=' .. tostring(result))
    else log('LOCAL_CONTROL error=' .. tostring(err)) end
end
log('LOCAL_CONTROL ready path=logs/control.lua')
