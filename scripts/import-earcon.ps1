[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [Alias('Input', 'Source')]
    [string]$InputPath,

    [ValidateSet('CIRCLE', 'X', 'SQUARE', 'TRIANGLE', 'L1', 'R1')]
    [Alias('Name')]
    [string]$Button,

    [Alias('Output')]
    [string]$OutputPath,

    [ValidateSet('mono', 'stereo')]
    [string]$Channels = 'mono',

    [int]$SampleRate = 22050,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

function Resolve-ExistingFile([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'Input path must not be empty.'
    }
    if (-not [IO.Path]::IsPathRooted($Path)) {
        $Path = Join-Path (Get-Location).Path $Path
    }
    $Path = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Input file not found: $Path"
    }
    return (Get-Item -LiteralPath $Path -ErrorAction Stop).FullName
}

function Resolve-OutputFile([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        if ([string]::IsNullOrWhiteSpace($Button)) {
            throw 'Specify -Button or provide -OutputPath.'
        }
        $lowerButton = $Button.ToLowerInvariant()
        $Path = Join-Path $repo (Join-Path 'sounds' ($lowerButton + '.wav'))
    }
    elseif (-not [IO.Path]::IsPathRooted($Path)) {
        $Path = Join-Path $repo $Path
    }

    $Path = [IO.Path]::GetFullPath($Path)
    if ([IO.Path]::GetExtension($Path).ToLowerInvariant() -ne '.wav') {
        throw "Output path must have a .wav extension: $Path"
    }
    return $Path
}

function Read-Little16([byte[]]$Bytes, [int]$Offset) {
    if ($Offset -lt 0 -or $Offset + 1 -ge $Bytes.Length) { return $null }
    return [int]$Bytes[$Offset] + [int]$Bytes[$Offset + 1] * 256
}

function Read-Little32([byte[]]$Bytes, [int]$Offset) {
    if ($Offset -lt 0 -or $Offset + 3 -ge $Bytes.Length) { return $null }
    [long]$value = [long]$Bytes[$Offset]
    $value += [long]$Bytes[$Offset + 1] * 0x100
    $value += [long]$Bytes[$Offset + 2] * 0x10000
    $value += [long]$Bytes[$Offset + 3] * 0x1000000
    return $value
}

function Read-PcmWavInfo([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 12) { throw 'file is shorter than a RIFF/WAVE header' }
    $ascii = [Text.Encoding]::ASCII
    if ($ascii.GetString($bytes, 0, 4) -ne 'RIFF') {
        throw 'missing RIFF header'
    }
    if ($ascii.GetString($bytes, 8, 4) -ne 'WAVE') {
        throw 'RIFF file is not a WAVE file'
    }

    $riffSize = Read-Little32 $bytes 4
    if ($null -eq $riffSize -or $riffSize -lt 4) {
        throw 'invalid RIFF size'
    }
    [long]$riffEnd = 8 + $riffSize
    if ($riffEnd -gt $bytes.Length) { throw 'RIFF data is truncated' }

    $format = $null
    $dataSize = $null
    [long]$cursor = 12
    while ($cursor -lt $riffEnd) {
        if ($cursor + 8 -gt $riffEnd) { throw 'truncated chunk header' }
        $chunkId = $ascii.GetString($bytes, [int]$cursor, 4)
        $chunkSize = Read-Little32 $bytes ([int]$cursor + 4)
        if ($null -eq $chunkSize) { throw 'truncated chunk size' }
        [long]$dataStart = $cursor + 8
        [long]$dataEnd = $dataStart + $chunkSize
        if ($dataEnd -gt $riffEnd) {
            throw 'chunk extends beyond RIFF data'
        }

        if ($chunkId -eq 'fmt ' -and $null -eq $format) {
            if ($chunkSize -lt 16) { throw 'fmt chunk is shorter than 16 bytes' }
            $format = [pscustomobject][ordered]@{
                AudioFormat = Read-Little16 $bytes ([int]$dataStart)
                Channels = Read-Little16 $bytes ([int]$dataStart + 2)
                SampleRate = Read-Little32 $bytes ([int]$dataStart + 4)
                ByteRate = Read-Little32 $bytes ([int]$dataStart + 8)
                BlockAlign = Read-Little16 $bytes ([int]$dataStart + 12)
                BitsPerSample = Read-Little16 $bytes ([int]$dataStart + 14)
            }
        }
        elseif ($chunkId -eq 'data' -and $null -eq $dataSize) {
            $dataSize = $chunkSize
        }

        $cursor = $dataEnd + ($chunkSize % 2)
    }
    if ($cursor -ne $riffEnd) { throw 'RIFF chunk layout is malformed' }
    if ($null -eq $format) { throw 'missing fmt chunk' }
    if ($null -eq $dataSize) { throw 'missing data chunk' }
    if ($format.AudioFormat -ne 1) { throw 'audio format is not uncompressed PCM' }
    if ($format.Channels -ne 1 -and $format.Channels -ne 2) {
        throw 'channels must be mono (1) or stereo (2)'
    }
    if ($format.SampleRate -lt 8000 -or $format.SampleRate -gt 192000) {
        throw 'sample rate must be between 8000 and 192000 Hz'
    }
    if ($format.BitsPerSample -ne 16) { throw 'bits per sample must be 16' }
    if ($format.BlockAlign -ne $format.Channels * 2) {
        throw 'block alignment does not match 16-bit PCM channels'
    }
    if ($format.ByteRate -ne $format.SampleRate * $format.BlockAlign) {
        throw 'byte rate does not match the PCM format'
    }
    if ($dataSize -eq 0 -or $dataSize % $format.BlockAlign -ne 0) {
        throw 'data chunk does not contain whole PCM frames'
    }

    [long]$frames = $dataSize / $format.BlockAlign
    if ($frames * 1000 -gt $format.SampleRate * 250) {
        $durationMs = 1000.0 * $frames / $format.SampleRate
        throw ('duration is {0:N1} ms; maximum is 250 ms' -f $durationMs)
    }
    return [pscustomobject][ordered]@{
        SampleRate = $format.SampleRate
        Channels = $format.Channels
        BitsPerSample = $format.BitsPerSample
        Frames = $frames
        DurationMs = 1000.0 * $frames / $format.SampleRate
    }
}

if ($SampleRate -lt 8000 -or $SampleRate -gt 192000) {
    throw '-SampleRate must be between 8000 and 192000 Hz.'
}
if ([string]::IsNullOrWhiteSpace($Button) -and [string]::IsNullOrWhiteSpace($OutputPath)) {
    throw 'Specify -Button or provide -OutputPath.'
}

$inputFile = Resolve-ExistingFile $InputPath
$outputFile = Resolve-OutputFile $OutputPath
$inputFull = [IO.Path]::GetFullPath($inputFile)
if ([string]::Equals($inputFull, $outputFile, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Input and output paths must be different.'
}
if ((Test-Path -LiteralPath $outputFile) -and -not $Force) {
    throw "Output already exists: $outputFile. Re-run with -Force to replace it."
}
if ((Test-Path -LiteralPath $outputFile) -and
    -not (Test-Path -LiteralPath $outputFile -PathType Leaf)) {
    throw "Output path is not a file: $outputFile"
}

$ffmpeg = Get-Command ffmpeg -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -eq $ffmpeg) {
    throw 'ffmpeg was not found on PATH; install it separately and try again. No download is performed.'
}
$ffmpegPath = $ffmpeg.Source

$outputDirectory = Split-Path -Parent $outputFile
if ([string]::IsNullOrWhiteSpace($outputDirectory)) { $outputDirectory = $repo }
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$tempName = '.{0}.{1}.tmp.wav' -f [IO.Path]::GetFileNameWithoutExtension($outputFile),
    ([Guid]::NewGuid().ToString('N'))
$tempFile = Join-Path $outputDirectory $tempName

$channelCount = if ($Channels -eq 'mono') { '1' } else { '2' }
$ffmpegArgs = @(
    '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
    '-i', $inputFile, '-vn', '-ac', $channelCount, '-ar', ([string]$SampleRate),
    '-c:a', 'pcm_s16le', '-f', 'wav', $tempFile
)

try {
    $ffmpegOutput = @(& $ffmpegPath @ffmpegArgs 2>&1)
    $ffmpegExitCode = $LASTEXITCODE
    if ($ffmpegExitCode -ne 0) {
        $details = ($ffmpegOutput | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        if ([string]::IsNullOrWhiteSpace($details)) { $details = 'ffmpeg returned no diagnostic output' }
        throw "ffmpeg conversion failed (exit code $ffmpegExitCode): $details"
    }
    if (-not (Test-Path -LiteralPath $tempFile -PathType Leaf)) {
        throw 'ffmpeg completed without creating a WAV file.'
    }

    $info = Read-PcmWavInfo $tempFile
    if ($info.SampleRate -ne $SampleRate -or $info.Channels -ne [int]$channelCount) {
        throw 'ffmpeg output did not match the requested sample rate or channel count.'
    }

    if ($Force) {
        Move-Item -LiteralPath $tempFile -Destination $outputFile -Force
    }
    else {
        Move-Item -LiteralPath $tempFile -Destination $outputFile
    }
    Write-Output ('Imported {0} -> {1} ({2} channels, {3} Hz, {4:N1} ms)' -f
        $inputFile, $outputFile, $info.Channels, $info.SampleRate, $info.DurationMs)
}
finally {
    if (Test-Path -LiteralPath $tempFile -PathType Leaf) {
        Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
    }
}
