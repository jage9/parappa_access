-- Longer interactive demo, initially paused for accessible launcher instructions.
stage1AudioFrames = 0 -- Interactive play has no timed exit.
stage1AudioPaused = not nativeGameStartup
stage1AudioLoadState = not nativeGameStartup
stage1AudioKeepGameRunning = nativeGameStartup == true
stage1ResultDetailedResearch = false -- Verified score/message reader probes are no longer needed for play.
local previousMono = PCSX.settings.spu.Mono
local previousGui = {}
for key, value in pairs({ShowMenu = false, ShowAssembly = false, FullWindowRender = true}) do
    previousGui[key] = PCSX.settings.gui[key]
    PCSX.settings.gui[key] = value
end
PCSX.log('PLAY_GUI menu=false assembly=false full_window=true\n')
local function restoreAudio()
    PCSX.settings.spu.Mono = previousMono
end
local function restorePreferences()
    restoreAudio()
    for key, value in pairs(previousGui) do PCSX.settings.gui[key] = value end
end
stage1PlayQuitting = PCSX.Events.createEventListener('Quitting', restorePreferences)
stage1PlayPause = PCSX.Events.createEventListener('ExecutionFlow::Pause', function()
    local sounds = stage1AudioSounds or nativeCueSounds
    if sounds and sounds.available then sounds.stop() end
end)
local audioFile = io.open('../../logs/demo-audio.txt', 'r')
if audioFile then
    local mode = audioFile:read('*a'):match('^%s*(.-)%s*$')
    audioFile:close()
    if mode == 'centered' then PCSX.settings.spu.Mono = true end
end
PCSX.log('DEMO_AUDIO mono=' .. tostring(PCSX.settings.spu.Mono) .. '\n')
function DrawImguiFrame()
    local path = '../../logs/demo-command.txt'
    local f = io.open(path, 'r')
    if not f then return end
    local command = f:read('*a'):match('^%s*(.-)%s*$')
    f:close(); os.remove(path)
    if command == 'resume' then
        if stage1FrameTiming then stage1FrameTiming.reset() end
        PCSX.resumeEmulator()
    elseif command == 'pause' then
        PCSX.pauseEmulator()
        if stage1AudioSounds then stage1AudioSounds.stop() end
    elseif command == 'score' then
        PCSX.pauseEmulator()
        if stage1AudioSounds then stage1AudioSounds.stop() end
        local reported = stageScoreRefs and stageScoreRefs.reportScore('score')
        if not reported then reported = stage1ResultRefs and stage1ResultRefs.reportScore and stage1ResultRefs.reportScore() end
        if not reported and nativeObserver then
            nativeObserver.announce('Score unavailable here. Game paused. Enter 2 in the console to resume.')
        end
    elseif command == 'quit' then restorePreferences(); PCSX.quit(0)
    else PCSX.log('DEMO_COMMAND_INVALID\n'); return end
    PCSX.log('DEMO_COMMAND ' .. command .. '\n')
end
local function attachStage1(profile)
    local ok, err = pcall(function()
        stage1AudioProfile = profile
        Support.extra.dofile('../../scripts/stage1-audio.lua')
        assert(stage1CursorOptions, 'Audio initialization failed')
        stage1CursorOptions.ready = function()
            local ok, err = stage1AudioSounds.prime()
            if not ok then PCSX.log('AUDIO_PREPARE_FAILED '..tostring(err)..'\n') end
            stageScoreContext = profile or Support.extra.dofile('../../scripts/stage-profiles.lua')[1]
            if stageScoreContext.stage == 1 then Support.extra.dofile('../../scripts/stage1-results.lua') end
            if stageScoreContext.stage > 1 then
                stageInputRefs = Support.extra.dofile('../../scripts/stage-input.lua')
            end
            Support.extra.dofile('../../scripts/frame-timing.lua')
        end
        local stop = stage1CursorOptions.stop
        stage1CursorOptions.stop = function()
            stageScoreContext = nil
            if stageInputRefs then stageInputRefs.stop('context_detached') end
            if stage1FrameTiming then stage1FrameTiming.stop() end
            if stage1ResultRefs and stage1ResultRefs.stop then stage1ResultRefs.stop() end
            if nativeObserver then nativeObserver.stage1Detached() end
            if not nativeGameStartup then restoreAudio() end
            if stop then stop() end
        end
    end)
    if not ok then
        restoreAudio()
        PCSX.log('DEMO_START_FAILED ' .. tostring(err) .. '\n')
        PCSX.nextTick(function() PCSX.quit(2) end)
    end
end
Support.extra.dofile('../../scripts/progress-checkpoints.lua')
Support.extra.dofile('../../scripts/post-win-research.lua')
Support.extra.dofile('../../scripts/stage-score.lua')
Support.extra.dofile('../../scripts/input-timing.lua')
if nativeGameStartup then
    nativeStage1Attach = attachStage1
    Support.extra.dofile('../../scripts/native-observer.lua')
    Support.extra.dofile('../../scripts/native-card-observer.lua')
    Support.extra.dofile('../../scripts/native-language-observer.lua')
    Support.extra.dofile('../../scripts/native-practice-observer.lua')
    laterStageRefs = {}
    for stage, profile in pairs(Support.extra.dofile('../../scripts/stage-profiles.lua')) do
        if stage > 1 and profile.introText then
            local p = profile
            laterStageRefs['intro' .. stage] = PCSX.addBreakpoint(p.entry - 0x2a0, 'Exec', 4, 'Native stage title card', function()
                local ffi = require('ffi'); local ram = PCSX.getMemPtr()
                local function word(a) return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0]) end
                if word(p.entry) ~= 0x27bdffc8 or word(p.loop) ~= (p.loopWord or 0x27bdffd0) or
                    word(p.entry - 0x2a0) ~= 0x27bdffd0 then return end
                local presentation = tonumber(PCSX.getRegisters().GPR.n.a2)
                if presentation == 0 then
                    nativeObserver.announce(p.introText, 'Enter Skip.')
                elseif p.stage == 6 and presentation == 0xffffffff then
                    nativeObserver.announce('Ending scene.', 'Enter Skip.')
                end
            end)
        end
        if stage > 1 and profile.verified then
            local p = profile
            laterStageRefs[stage] = PCSX.addBreakpoint(p.entry, 'Exec', 4, 'Native stage entry', function()
                local ffi = require('ffi'); local ram = PCSX.getMemPtr()
                local function word(a) return tonumber(ffi.cast('uint32_t*', ram + a - 0x80000000)[0]) end
                if word(p.entry) ~= 0x27bdffc8 or word(p.loop) ~= (p.loopWord or 0x27bdffd0) or
                    bit.band(word(0x800916d0), 0xffff) ~= 0 then return end
                if stage1CursorProbe and stage1CursorProbe.isActive() then
                    stageScoreContext = p
                    nativeObserver.setHint('')
                    stage1CursorProbe.resetResearchWindow()
                    if stageInputRefs then stageInputRefs.reset() end
                    return
                end
                nativeObserver.announce('Stage ' .. p.stage .. '. ' .. p.teacher .. '.')
                attachStage1(p)
            end)
        end
    end
else
    attachStage1()
end
