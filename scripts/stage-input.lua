-- Passive received-controller logger for verified stages 2-6.
-- Set stageScoreContext before loading, or stageInputProfile for an explicit profile.
local ffi = require('ffi')
local ram = PCSX.getMemPtr()
local function u32(a) return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0]) end

local profile = stageInputProfile or stageScoreContext
assert(profile and profile.verified and profile.stage >= 2 and profile.stage <= 6,
    'Verified stage 2-6 profile required')
local site = profile.entry + 0x484
local refs = {profile=profile, frame=0, transitions=0, stopped=false, previous=nil, listeners={}}

local function sitePresent()
    return u32(site - 8) == 0x0c00d544 and u32(site - 4) == 0x34040001 and
        u32(site) == 0x00402021
end
local function context()
    return u32(profile.entry) == 0x27bdffc8 and
        u32(profile.loop) == (profile.loopWord or 0x27bdffd0) and
        u32(0x800943d0) == profile.grid and u32(0x800943d4) == profile.count and
        bit.band(u32(0x800916d0), 0xffff) == 0
end
local function disable()
    if refs.input then pcall(function() refs.input:disable() end) end
end
local function stop(reason)
    if refs.stopped then return end
    refs.stopped = true
    disable()
    -- Keep the listener rooted and inert: Redux dispatch walks its live list.
    -- Removing a listener inside a callback can invalidate that traversal.
    if reason then
        PCSX.log(string.format('STAGE_INPUT_STOP stage=%d reason=%s frame=%d transitions=%d\n',
            profile.stage, reason, refs.frame, refs.transitions))
    end
end
local function onVsync()
    if refs.stopped or not context() then return end
    refs.frame = refs.frame + 1
    if refs.frame >= 18000 then stop('frame_limit') end
end
refs.stop = function(reason) stop(reason or 'stopped') end
refs.reset = function()
    refs.frame, refs.transitions, refs.previous, refs.stopped = 0, 0, nil, false
    if refs.input then refs.input:enable() end
    if not refs.vsync then
        refs.vsync = PCSX.Events.createEventListener('GPU::Vsync', onVsync)
        refs.listeners[#refs.listeners + 1] = refs.vsync
    end
end
refs.isActive = function() return not refs.stopped end

refs.input = PCSX.addBreakpoint(site, 'Exec', 4, 'Observe received controller mask', function()
    if refs.stopped or refs.frame >= 18000 or not context() or not sitePresent() then return end
    local hostNs = tonumber(luv.hrtime())
    local mask = tonumber(PCSX.getRegisters().GPR.n.v0) or 0
    if mask == refs.previous then return end
    refs.previous = mask
    refs.transitions = refs.transitions + 1
    PCSX.log(string.format('STAGE_INPUT stage=%d frame=%d tick=%d mask=%08x transition=%d host_ns=%.0f\n',
        profile.stage, refs.frame, u32(0x801c364c), mask, refs.transitions, hostNs))
    if refs.transitions >= 512 then stop('transition_limit') end
end)
refs.vsync = PCSX.Events.createEventListener('GPU::Vsync', onVsync)
refs.listeners[#refs.listeners + 1] = refs.vsync

return refs
