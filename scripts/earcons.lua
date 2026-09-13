-- Small, opt-in button earcons for LuaJIT on Windows.
--
-- A replacement WAV may be supplied in ../../sounds (the repository's
-- sounds/ directory when Redux is launched by run-redux.ps1). Files are read
-- and validated while this module is loaded. Playback only looks up an
-- already-cached memory buffer, so a note callback never performs I/O.

local M = {
    available = false,
    sources = {},
    sourceInfo = {},
    soundDirectory = '../../sounds',
}

local backendError = 'WinMM PlaySoundA is unavailable'
local buttons = {'CIRCLE', 'X', 'SQUARE', 'TRIANGLE', 'L1', 'R1'}
-- The option file is written by the accessibility menu.  Keeping the
-- default off makes standalone probes and exporters preserve the exact
-- source bytes until panning is deliberately enabled.
local panPositions = {
    TRIANGLE = -0.35,
    L1 = -0.6,
    SQUARE = -0.8,
    X = 0.35,
    R1 = 0.6,
    CIRCLE = 0.8,
}
local panEnabled = false
local panOption = io.open('../../logs/demo-panning.txt', 'r')
if panOption then
    local setting = panOption:read('*a')
    panOption:close()
    panEnabled = string.lower(setting or ''):match('^%s*on%s*$') ~= nil
end
M.panEnabled = panEnabled
M.panPositions = panPositions
local entries = {}
local loadErrors = {}

local function little16(value)
    local lo = value % 0x100
    local hi = math.floor(value / 0x100) % 0x100
    return string.char(lo, hi)
end

local function little32(value)
    local b1 = value % 0x100
    value = math.floor(value / 0x100)
    local b2 = value % 0x100
    value = math.floor(value / 0x100)
    local b3 = value % 0x100
    value = math.floor(value / 0x100)
    local b4 = value % 0x100
    return string.char(b1, b2, b3, b4)
end

local function readLittle16(bytes, position)
    local first, second = bytes:byte(position, position + 1)
    if not second then return nil end
    return first + second * 0x100
end

local function readSignedLittle16(bytes, position)
    local value = readLittle16(bytes, position)
    if not value then return nil end
    if value >= 0x8000 then value = value - 0x10000 end
    return value
end

local function readLittle32(bytes, position)
    local b1, b2, b3, b4 = bytes:byte(position, position + 3)
    if not b4 then return nil end
    return b1 + b2 * 0x100 + b3 * 0x10000 + b4 * 0x1000000
end

local function invalidWav(reason)
    return nil, reason
end

-- Validate the subset accepted by PlaySoundA and by the accessibility
-- design: uncompressed mono/stereo PCM with a bounded duration.
local MIN_SAMPLE_RATE = 8000
local MAX_SAMPLE_RATE = 192000
local MAX_DURATION_MS = 250

local function parseWav(bytes)
    if type(bytes) ~= 'string' or #bytes < 12 then
        return invalidWav('file is shorter than a RIFF/WAVE header')
    end
    if bytes:sub(1, 4) ~= 'RIFF' then
        return invalidWav('missing RIFF header')
    end
    if bytes:sub(9, 12) ~= 'WAVE' then
        return invalidWav('RIFF file is not a WAVE file')
    end

    local riffSize = readLittle32(bytes, 5)
    if not riffSize or riffSize < 4 then
        return invalidWav('invalid RIFF size')
    end
    local riffEnd = 8 + riffSize
    if riffEnd > #bytes then
        return invalidWav('RIFF data is truncated')
    end

    local format
    local dataSize
    local dataOffset
    local cursor = 13
    while cursor <= riffEnd do
        if cursor + 7 > riffEnd then
            return invalidWav('truncated chunk header')
        end
        local chunkId = bytes:sub(cursor, cursor + 3)
        local chunkSize = readLittle32(bytes, cursor + 4)
        if not chunkSize then
            return invalidWav('truncated chunk size')
        end
        local dataStart = cursor + 8
        local dataEnd = dataStart + chunkSize
        if dataEnd > riffEnd + 1 then
            return invalidWav('chunk extends beyond RIFF data')
        end

        if chunkId == 'fmt ' and not format then
            if chunkSize < 16 then
                return invalidWav('fmt chunk is shorter than 16 bytes')
            end
            format = {
                audioFormat = readLittle16(bytes, dataStart),
                channels = readLittle16(bytes, dataStart + 2),
                sampleRate = readLittle32(bytes, dataStart + 4),
                byteRate = readLittle32(bytes, dataStart + 8),
                blockAlign = readLittle16(bytes, dataStart + 12),
                bitsPerSample = readLittle16(bytes, dataStart + 14),
            }
        elseif chunkId == 'data' and not dataSize then
            dataSize = chunkSize
            dataOffset = dataStart
        end

        -- RIFF chunks are word aligned; a pad byte follows an odd-sized one.
        cursor = dataEnd + (chunkSize % 2)
    end

    if cursor ~= riffEnd + 1 then
        return invalidWav('RIFF chunk layout is malformed')
    end
    if not format then
        return invalidWav('missing fmt chunk')
    end
    if not dataSize then
        return invalidWav('missing data chunk')
    end
    if format.audioFormat ~= 1 then
        return invalidWav('audio format is not uncompressed PCM')
    end
    if format.channels ~= 1 and format.channels ~= 2 then
        return invalidWav('channels must be mono (1) or stereo (2)')
    end
    if not format.sampleRate or format.sampleRate < MIN_SAMPLE_RATE
        or format.sampleRate > MAX_SAMPLE_RATE then
        return invalidWav(string.format('sample rate must be between %d and %d Hz',
            MIN_SAMPLE_RATE, MAX_SAMPLE_RATE))
    end
    if format.bitsPerSample ~= 16 and format.bitsPerSample ~= 24 then
        return invalidWav('bits per sample must be 16 or 24')
    end
    if format.blockAlign ~= format.channels * (format.bitsPerSample / 8) then
        return invalidWav('block alignment does not match PCM channels and bit depth')
    end
    if format.byteRate ~= format.sampleRate * format.blockAlign then
        return invalidWav('byte rate does not match the PCM format')
    end
    if dataSize == 0 or dataSize % format.blockAlign ~= 0 then
        return invalidWav('data chunk does not contain whole PCM frames')
    end

    local frames = dataSize / format.blockAlign
    if frames * 1000 > format.sampleRate * MAX_DURATION_MS then
        return invalidWav(string.format('duration is %.1f ms; maximum is %d ms',
            frames * 1000 / format.sampleRate, MAX_DURATION_MS))
    end

    return {
        sampleRate = format.sampleRate,
        channels = format.channels,
        bitsPerSample = format.bitsPerSample,
        frames = frames,
        durationMs = frames * 1000 / format.sampleRate,
        dataOffset = dataOffset,
        dataSize = dataSize,
    }
end

-- 112 ms, mono, 16-bit PCM at 22.05 kHz for the generated defaults. The
-- source replacements may be mono or stereo, but keep the same short limit.
local sampleRate = 22050
local duration = 0.112
local tau = math.pi * 2

local SND_ASYNC = 0x0001
local SND_NODEFAULT = 0x0002
local SND_MEMORY = 0x0004
local playFlags = SND_ASYNC + SND_MEMORY + SND_NODEFAULT

-- Integrate a frequency that rises linearly to a peak and then falls
-- linearly. Integrating the two line segments keeps the Circle siren's phase
-- continuous and avoids the roughness of multiplying f(t) by t.
local function integratedTriangularChirp(time, startFrequency, peakFrequency,
        endFrequency)
    local half = duration * 0.5
    if time <= half then
        return startFrequency * time
            + 0.5 * (peakFrequency - startFrequency) * time * time / half
    end

    local firstHalf = startFrequency * half
        + 0.5 * (peakFrequency - startFrequency) * half
    local secondTime = time - half
    return firstHalf + peakFrequency * secondTime
        + 0.5 * (endFrequency - peakFrequency)
            * secondTime * secondTime / half
end

local function phaseFor(spec, time)
    if spec.chirp == 'triangular' then
        return integratedTriangularChirp(time, spec.startFrequency,
            spec.peakFrequency, spec.endFrequency)
    end
    return spec.startFrequency * time
        + 0.5 * (spec.glide or 0) * time * time / duration
end

local function makeWav(spec)
    local frames = math.floor(sampleRate * duration)
    local parts = {
        'RIFF', little32(36 + frames * 2), 'WAVE',
        'fmt ', little32(16), little16(1), little16(1),
        little32(sampleRate), little32(sampleRate * 2), little16(2),
        little16(16), 'data', little32(frames * 2),
    }

    for index = 0, frames - 1 do
        local time = index / sampleRate
        local phase = phaseFor(spec, time)
        local attack = math.min(1, time / spec.attack)
        local release = math.min(1, (duration - time) / spec.release)
        local envelope = math.max(0, attack * release)
        local wave
        if spec.kind == 'square' then
            local fraction = phase - math.floor(phase)
            wave = (fraction < 0.5 and 1 or -1)
                + (spec.overtone or 0) * math.sin(tau * phase * 2)
        elseif spec.kind == 'sawtooth' then
            wave = 2 * (phase - math.floor(phase)) - 1
        else
            wave = math.sin(tau * phase)
                + (spec.overtone or 0) * math.sin(tau * phase * 2)
        end
        local sample = math.floor(32767 * spec.amplitude * envelope * wave)
        if sample > 32767 then sample = 32767 end
        if sample < -32768 then sample = -32768 end
        if sample < 0 then sample = sample + 0x10000 end
        parts[#parts + 1] = string.char(sample % 0x100,
            math.floor(sample / 0x100) % 0x100)
    end

    return table.concat(parts)
end

local function encodeSignedLittle16(value)
    if value >= 0 then
        value = math.floor(value + 0.5)
    else
        value = math.ceil(value - 0.5)
    end
    if value > 32767 then value = 32767 end
    if value < -32768 then value = -32768 end
    if value < 0 then value = value + 0x10000 end
    return string.char(value % 0x100, math.floor(value / 0x100) % 0x100)
end

-- Convert a source to canonical stereo PCM and apply equal-power panning.
-- Stereo replacements are intentionally reduced to one centered sample per
-- frame before the requested position is applied. This keeps the six
-- button positions predictable and leaves the source file itself untouched.
local function makePannedWav(source, pan)
    local angle = (pan + 1) * math.pi * 0.25
    local leftGain = math.cos(angle)
    local rightGain = math.sin(angle)
    local bytes = source.bytes
    local dataStart = source.dataOffset
    local parts = {
        'RIFF', little32(36 + source.frames * 4), 'WAVE',
        'fmt ', little32(16), little16(1), little16(2),
        little32(source.sampleRate), little32(source.sampleRate * 4),
        little16(4), little16(16), 'data', little32(source.frames * 4),
    }
    for frame = 0, source.frames - 1 do
        local position = dataStart + frame * source.channels * 2
        local sample = readSignedLittle16(bytes, position)
        if not sample then return nil, 'panning source data is truncated' end
        if source.channels == 2 then
            local right = readSignedLittle16(bytes, position + 2)
            if not right then return nil, 'panning source data is truncated' end
            sample = (sample + right) * 0.5
        end
        parts[#parts + 1] = encodeSignedLittle16(sample * leftGain)
        parts[#parts + 1] = encodeSignedLittle16(sample * rightGain)
    end
    return table.concat(parts)
end

local specs = {
    -- Circle is a sawtooth up/down siren. The triangular frequency curve is
    -- integrated above, rather than using an instantaneous phase shortcut.
    CIRCLE = {
        kind = 'sawtooth', chirp = 'triangular', startFrequency = 330,
        peakFrequency = 760, endFrequency = 330, overtone = 0,
        amplitude = 0.3528, attack = 0.004, release = 0.016,
    },
    -- X is a high square-wave tone with no added noise.
    X = {
        kind = 'square', startFrequency = 1250, glide = 0,
        overtone = 0, amplitude = 0.3528, attack = 0.002, release = 0.018,
    },
    SQUARE = {
        kind = 'square', startFrequency = 196, glide = 20,
        overtone = 0.10, amplitude = 0.252, attack = 0.003, release = 0.016,
    },
    -- Triangle uses the middle pitch and a square-wave timbre.
    TRIANGLE = {
        kind = 'square', startFrequency = 520, glide = 0,
        overtone = 0, amplitude = 0.252, attack = 0.002, release = 0.014,
    },
    L1 = {
        kind = 'sine', startFrequency = 660, glide = -360,
        overtone = 0.18, amplitude = 0.252, attack = 0.002, release = 0.018,
    },
    R1 = {
        kind = 'sine', startFrequency = 270, glide = 520,
        overtone = 0.16, amplitude = 0.252, attack = 0.002, release = 0.014,
    },
}

local function isMissingFileError(errorText)
    local text = string.lower(tostring(errorText or ''))
    return text == ''
        or text:find('no such file', 1, true) ~= nil
        or text:find('cannot find', 1, true) ~= nil
        or text:find('does not exist', 1, true) ~= nil
        or text:find('not found', 1, true) ~= nil
end

local function sourceFailure(kind, path, reason)
    return {
        kind = kind,
        path = path,
        error = reason,
    }
end

local function loadReplacement(path)
    local callOk, file, openError = pcall(function()
        return io.open(path, 'rb')
    end)
    if not callOk then
        return sourceFailure('file', path,
            'Could not open earcon WAV "' .. path .. '": ' .. tostring(file))
    end
    if not file then
        if isMissingFileError(openError) then return nil end
        return sourceFailure('file', path,
            'Could not open earcon WAV "' .. path .. '": ' .. tostring(openError))
    end

    local readOk, bytes, readError = pcall(function()
        return file:read('*a')
    end)
    local closeOk, closeResult = pcall(function()
        return file:close()
    end)
    if not readOk then
        return sourceFailure('file', path,
            'Could not read earcon WAV "' .. path .. '": ' .. tostring(bytes))
    end
    if not bytes then
        return sourceFailure('file', path,
            'Could not read earcon WAV "' .. path .. '": ' .. tostring(readError))
    end
    if not closeOk or not closeResult then
        local reason = closeOk and tostring(closeResult) or tostring(closeResult)
        return sourceFailure('file', path,
            'Could not close earcon WAV "' .. path .. '": ' .. reason)
    end

    local info, validationError = parseWav(bytes)
    if not info then
        return sourceFailure('file', path,
            'Invalid earcon WAV "' .. path .. '": ' .. tostring(validationError))
    end
    local originalBits = info.bitsPerSample
    if originalBits == 24 then
        local size = info.frames * info.channels * 2
        local parts = {'RIFF', little32(36 + size), 'WAVEfmt ', little32(16),
            little16(1), little16(info.channels), little32(info.sampleRate),
            little32(info.sampleRate * info.channels * 2), little16(info.channels * 2),
            little16(16), 'data', little32(size)}
        for position = info.dataOffset, info.dataOffset + info.dataSize - 1, 3 do
            local lo, mid, hi = bytes:byte(position, position + 2)
            local sample = lo + mid * 256 + hi * 65536
            if sample >= 8388608 then sample = sample - 16777216 end
            parts[#parts + 1] = encodeSignedLittle16(sample / 256)
        end
        bytes = table.concat(parts)
        info = assert(parseWav(bytes))
    end
    info.originalBitsPerSample = originalBits
    info.kind = 'file'
    info.path = path
    info.bytes = bytes
    return info
end

local function applyPanning(source, name)
    if not panEnabled or source.error then return source end
    local pan = panPositions[name]
    if pan == nil then return source end

    local bytes, panningError = makePannedWav(source, pan)
    if not bytes then
        source.error = 'Could not pan earcon "' .. name .. '": '
            .. tostring(panningError)
        return source
    end
    local info, validationError = parseWav(bytes)
    if not info then
        source.error = 'Panned earcon "' .. name .. '" is invalid: '
            .. tostring(validationError)
        return source
    end
    info.kind = source.kind
    info.path = source.path
    info.fallbackPath = source.fallbackPath
    info.bytes = bytes
    info.pan = pan
    info.panEnabled = true
    info.originalChannels = source.channels
    info.originalBitsPerSample = source.originalBitsPerSample or source.bitsPerSample
    return info
end

-- Resolve every source up front. A missing optional file gets a generated
-- sound; an existing but malformed file remains an error and never falls
-- through to the generated sound.
for _, name in ipairs(buttons) do
    local path = M.soundDirectory .. '/' .. string.lower(name) .. '.wav'
    local source = loadReplacement(path)
    if not source then
        local bytes = makeWav(specs[name])
        local info, validationError = parseWav(bytes)
        if not info then
            source = sourceFailure('generated', path,
                'Generated earcon is invalid: ' .. tostring(validationError))
        else
            info.kind = 'generated'
            info.fallbackPath = path
            info.bytes = bytes
            source = info
        end
    end
    source = applyPanning(source, name)
    entries[name] = source
    M.sources[name] = source.kind
    M.sourceInfo[name] = {
        kind = source.kind,
        path = source.path,
        fallbackPath = source.fallbackPath,
        sampleRate = source.sampleRate,
        channels = source.channels,
        bitsPerSample = source.bitsPerSample,
        originalBitsPerSample = source.originalBitsPerSample or source.bitsPerSample,
        frames = source.frames,
        durationMs = source.durationMs,
        pan = source.pan,
        panEnabled = source.panEnabled or false,
        originalChannels = source.originalChannels or source.channels,
        error = source.error,
    }
    if source.error then loadErrors[#loadErrors + 1] = source.error end
end

if #loadErrors > 0 then
    M.loadErrors = loadErrors
    M.loadError = table.concat(loadErrors, '; ')
    backendError = 'Earcon source validation failed: ' .. M.loadError
end

-- Export the exact bytes selected for playback. This function performs no
-- file access; callers such as export-earcons.lua can choose to write them.
function M.wav(name)
    if type(name) ~= 'string' then return nil, 'unknown button' end
    name = string.upper(name)
    local entry = entries[name]
    if not entry then return nil, 'unknown button: ' .. name end
    if entry.error then return nil, entry.error end
    return entry.bytes
end

-- Return the source kind and metadata without exposing the mutable internal
-- byte buffer. M.sources remains a simple name -> kind map for callers that
-- only need to report whether a replacement was selected.
function M.source(name)
    if type(name) ~= 'string' then return nil, 'unknown button' end
    name = string.upper(name)
    local info = M.sourceInfo[name]
    if not info then return nil, 'unknown button: ' .. name end
    return info.kind, info
end

local ffiOk, ffi = pcall(require, 'ffi')
if ffiOk and ffi.os == 'Windows' then
    -- Use primitive types in the declaration so this module does not compete
    -- with another script's Windows typedefs. Win32 DWORD remains 32-bit on
    -- Windows x64, while the handle is pointer-sized.
    local cdefOk, cdefError = pcall(ffi.cdef, [[
        int PlaySoundA(const char *pszSound, void *hmod,
                       unsigned long fdwSound);
    ]])
    -- A second dofile in one Lua state reports a harmless declaration
    -- redefinition. The declaration is still available in that case.
    local alreadyDeclared = not cdefOk
        and tostring(cdefError):lower():find('redef', 1, true) ~= nil
    if cdefOk or alreadyDeclared then
        local loadOk, winmm = pcall(ffi.load, 'winmm')
        if loadOk then
            local sounds = {}
            for name, entry in pairs(entries) do
                if not entry.error then
                    local buffer = ffi.new('unsigned char[?]', #entry.bytes)
                    ffi.copy(buffer, entry.bytes, #entry.bytes)
                    -- Keep both the owning array and pointer alive for the
                    -- whole module lifetime; PlaySoundA is asynchronous.
                    sounds[name] = {
                        buffer = buffer,
                        pointer = ffi.cast('const char *', buffer),
                    }
                end
            end

            -- A malformed replacement makes the selected source set
            -- unavailable as a whole. This prevents a caller from believing
            -- it received its chosen file while still giving play() the
            -- exact path-specific error for the requested button.
            M.available = #loadErrors == 0
            local primed, primeBuffer = false, nil
            -- Prepare WinMM with silence before the first demonstration. This
            -- is not a cue and does not alter the timing of any note event.
            function M.prime()
                if primed then return true end
                if not M.available then return false, M.loadError end
                local source = entries.TRIANGLE
                local bytes = source.bytes:sub(1, source.dataOffset - 1)
                    .. string.rep('\0', source.dataSize)
                    .. source.bytes:sub(source.dataOffset + source.dataSize)
                primeBuffer = ffi.new('unsigned char[?]', #bytes)
                ffi.copy(primeBuffer, bytes, #bytes)
                local ok, result = pcall(winmm.PlaySoundA,
                    ffi.cast('const char *', primeBuffer), nil, playFlags)
                if not ok or result == 0 then return false, 'Silent playback preparation failed' end
                primed = true
                return true
            end
            function M.play(name)
                if type(name) ~= 'string' then
                    return false, 'unknown button'
                end
                name = string.upper(name)
                local entry = entries[name]
                if entry == nil then
                    return false, 'unknown button: ' .. name
                end
                if entry.error then return false, entry.error end
                local sound = sounds[name]
                if not sound then return false, 'earcon is not cached: ' .. name end
                local ok, result = pcall(winmm.PlaySoundA, sound.pointer, nil,
                    playFlags)
                if not ok or result == 0 then
                    return false, 'PlaySoundA failed for ' .. name
                end
                return true
            end

            function M.stop()
                local ok, result = pcall(winmm.PlaySoundA, nil, nil, 0)
                if not ok or result == 0 then
                    return false, 'PlaySoundA stop failed'
                end
                return true
            end
        else
            backendError = 'WinMM could not be loaded: ' .. tostring(winmm)
        end
    else
        backendError = 'PlaySoundA declaration failed: ' .. tostring(cdefError)
    end
elseif not ffiOk then
    backendError = 'LuaJIT FFI is unavailable: ' .. tostring(ffi)
elseif ffi.os ~= 'Windows' then
    backendError = 'WinMM is unsupported on ' .. tostring(ffi.os)
end

if not M.available then
    M.play = function(name)
        if type(name) == 'string' then
            local entry = entries[string.upper(name)]
            if entry and entry.error then return false, entry.error end
        end
        return false, backendError
    end
    M.stop = function()
        return false, backendError
    end
end

return M
