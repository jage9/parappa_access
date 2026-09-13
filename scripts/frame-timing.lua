-- Bounded wall-clock diagnostics only. No game state, input or cue changes.
local refs = {}
stage1FrameTiming = refs
local previous, frames, gaps, reported, maximum = nil, 0, 0, 0, 0
local windowIntervals, windowElapsed, windowMaximum, windowOver25 = 0, 0, 0, 0
local windowWarmup = 0
local windowsReported = 0
local lastShowMenu, lastShowAssembly = nil, nil
local guiChangesReported = 0
local WINDOW_SIZE, WINDOW_CAP, GUI_CHANGE_CAP = 120, 180, 60
local stopped = false
local function resetWindow()
    windowIntervals, windowElapsed, windowMaximum, windowOver25 = 0, 0, 0, 0
end
local function observeGui()
    -- Some reduced test mocks and headless runs have no GUI settings table.
    local settings = PCSX.settings
    local gui = settings and settings.gui
    if not gui then return end
    local showMenu, showAssembly = gui.ShowMenu, gui.ShowAssembly
    if showMenu == nil and showAssembly == nil then return end
    if showMenu == lastShowMenu and showAssembly == lastShowAssembly then return end
    lastShowMenu, lastShowAssembly = showMenu, showAssembly
    if guiChangesReported >= GUI_CHANGE_CAP then return end
    guiChangesReported = guiChangesReported + 1
    PCSX.log(string.format('FRAME_TIMING_GUI frame=%d show_menu=%s show_assembly=%s\n',
        frames, tostring(showMenu), tostring(showAssembly)))
end
function refs.reset()
    previous = nil -- Deliberate pause/resume is not a performance gap.
    windowWarmup = 0
    resetWindow()
end
function refs.stop()
    if stopped then return end
    stopped = true
    PCSX.log(string.format('FRAME_TIMING_SUMMARY frames=%d gaps_over_50ms=%d max_gap_ms=%.2f\n',
        frames, gaps, maximum))
end
refs.vsync = PCSX.Events.createEventListener('GPU::Vsync', function()
    if stopped then return end
    local now = luv.hrtime()
    frames = frames + 1
    observeGui()
    local gap
    if previous then
        gap = tonumber(now - previous) / 1000000
    end
    if gap and frames > 120 then
        maximum = math.max(maximum, gap)
        if gap > 50 then
            gaps = gaps + 1
            if reported < 60 then
                reported = reported + 1
                PCSX.log(string.format('FRAME_TIMING_GAP frame=%d gap_ms=%.2f\n', frames, gap))
            end
        end
    end
    if gap and windowsReported < WINDOW_CAP then
        if windowWarmup < WINDOW_SIZE then
            -- Keep the existing startup grace period; the first cadence
            -- window begins after 120 settled vsyncs.
            windowWarmup = windowWarmup + 1
        else
            windowIntervals = windowIntervals + 1
            windowElapsed = windowElapsed + gap
            windowMaximum = math.max(windowMaximum, gap)
            if gap > 25 then windowOver25 = windowOver25 + 1 end
            if windowIntervals == WINDOW_SIZE then
                windowsReported = windowsReported + 1
                PCSX.log(string.format(
                    'FRAME_TIMING_WINDOW window=%d frame=%d elapsed_ms=%.2f avg_ms=%.2f max_ms=%.2f over25=%d\n',
                    windowsReported, frames, windowElapsed, windowElapsed / windowIntervals,
                    windowMaximum, windowOver25))
                resetWindow()
            end
        end
    end
    previous = now
end)
