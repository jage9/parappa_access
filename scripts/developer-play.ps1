[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateRange(1, 6)][int]$Stage,
    [Parameter(Mandatory = $true)][string]$StatePath,
    [ValidateRange(1, 12)][int]$Attempts = 8,
    [string[]]$SeedLog
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$logsRoot = [IO.Path]::GetFullPath((Join-Path $repo 'logs')).TrimEnd('\')
$working = Join-Path $repo 'tools/pcsx-redux'
$launcher = Join-Path $repo 'scripts/run-redux.ps1'
$durationSeconds = 600

function Resolve-LogsFile([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'A logs path was empty.' }
    $candidate = if ([IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $repo $Path }
    $full = [IO.Path]::GetFullPath($candidate)
    $prefix = $logsRoot + '\'
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path must be inside logs/: $Path"
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw "File not found: $full" }
    return (Get-Item -LiteralPath $full -ErrorAction Stop).FullName
}

function New-AttemptLog {
    do {
        $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
        $name = 'play-stage{0}-developer-{1}-{2}.log' -f $Stage, $stamp, ([Guid]::NewGuid().ToString('N'))
        $full = Join-Path $logsRoot $name
    } while (Test-Path -LiteralPath $full)
    return $full
}

function Add-Response([hashtable]$Events, [Int64]$Tick, [int]$Lane, [string]$Source) {
    if ($Tick -lt 0 -or $Tick -gt 1000000000) { throw "Invalid BOT_RESPONSE tick in ${Source}: ${Tick}" }
    if ($Lane -lt 1 -or $Lane -gt 8) { throw "Invalid BOT_RESPONSE lane in ${Source}: ${Lane}" }
    if ($Events.ContainsKey($Tick)) {
        $old = [int]$Events[$Tick]
        $sameAlias = (($old -in 5, 6) -and ($Lane -in 5, 6)) -or
            (($old -in 7, 8) -and ($Lane -in 7, 8))
        if ($old -ne $Lane -and -not $sameAlias) {
            throw "Conflicting BOT_RESPONSE tick ${Tick}: lane $old versus $Lane in ${Source}"
        }
        return
    }
    $Events[$Tick] = $Lane
}

function Read-Responses([hashtable]$Events, [string]$Path) {
    foreach ($line in Get-Content -LiteralPath $Path) {
        $m = [regex]::Match($line, '^\s*BOT_RESPONSE\s+tick=(\d+)\s+lane=(\d+)\b')
        if ($m.Success) {
            Add-Response $Events ([Int64]::Parse($m.Groups[1].Value)) ([int]$m.Groups[2].Value) $Path
        }
    }
}

function Schedule-Lua([hashtable]$Events) {
    $parts = foreach ($entry in ($Events.GetEnumerator() | Sort-Object { [Int64]$_.Key })) {
        [string]::Format([Globalization.CultureInfo]::InvariantCulture, '{{{0},{1}}}',
            [Int64]$entry.Key, [int]$entry.Value)
    }
    return '{' + ($parts -join ',') + '}'
}

function Lua-Long([string]$Value) {
    if ($Value.Contains(']=]')) { throw 'Path contains an unsafe Lua long-bracket delimiter.' }
    return '[=[' + $Value + ']=]'
}

$stateFull = Resolve-LogsFile $StatePath
$stateRel = '../../logs/' + $stateFull.Substring(($logsRoot + '\').Length).Replace('\', '/')
if (-not $stateRel.StartsWith('../../logs/', [StringComparison]::OrdinalIgnoreCase) -or
    $stateRel.Substring(11).Contains('..')) { throw 'StatePath must be a local file under logs/.' }
$events = @{}
foreach ($seed in @($SeedLog)) {
    if ($null -ne $seed -and -not [string]::IsNullOrWhiteSpace($seed)) {
        Read-Responses $events (Resolve-LogsFile $seed)
    }
}
[IO.Directory]::CreateDirectory($logsRoot) | Out-Null
$attemptLogs = @()

for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    $attemptLog = New-AttemptLog
    $attemptLogs += $attemptLog
    $tempLua = [IO.Path]::ChangeExtension($attemptLog, '.lua')
    if (Test-Path -LiteralPath $tempLua) { throw "Attempt configuration already exists: $tempLua" }
    $seedLua = Schedule-Lua $events
    $lua = "developerPlayConfig={stage=$Stage,statePath=$(Lua-Long $stateRel),maxAttempts=1,seed=$seedLua}`n" +
        "Support.extra.dofile('../../scripts/developer-play.lua')`n"
    [IO.File]::WriteAllText($tempLua, $lua, (New-Object -TypeName Text.UTF8Encoding -ArgumentList $false))
    $launchError = $null
    Write-Host "Developer stage $Stage attempt $attempt/$Attempts; learned=$($events.Count); log=$attemptLog"
    try {
        & $launcher -Debugger -Wait -DurationSeconds $durationSeconds -Lua $tempLua -Log $attemptLog *> $null
    } catch {
        $launchError = $_.Exception.Message
    }
    if (-not (Test-Path -LiteralPath $attemptLog -PathType Leaf)) {
        throw "Attempt $attempt produced no log. $launchError"
    }
    $lines = @(Get-Content -LiteralPath $attemptLog)
    if ($lines -match 'BOT_GATE_FAILED|BOT_START_FAILED') { throw "Attempt $attempt failed its checks; see $attemptLog" }
    if ($lines -match 'BOT_TIMEOUT|DURATION_COMPLETE') { throw "Attempt $attempt timed out; see $attemptLog" }
    $result = $null; $resultLine = $null
    foreach ($line in $lines) {
        $m = [regex]::Match($line, 'BOT_RESULT\s+trial=\d+\s+result=(\d+)\b')
        if ($m.Success) { $result = [int]$m.Groups[1].Value; $resultLine = $line }
    }
    if ($null -eq $result) { throw "Attempt $attempt produced no BOT_RESULT. $launchError See $attemptLog" }
    if ($launchError) { throw "Attempt $attempt launcher failure: $launchError See $attemptLog" }
    Read-Responses $events $attemptLog
    if ($result -eq 1) {
        $marker = $null
        foreach ($line in $lines) {
            $m = [regex]::Match($line, 'BOT_CLEAR_CHECKPOINT\s+(\S+)')
            if ($m.Success) { $marker = $m.Groups[1].Value }
        }
        if ($null -eq $marker -or -not $marker.StartsWith('../../logs/', [StringComparison]::OrdinalIgnoreCase) -or
            $marker.Substring(11).Contains('..')) { throw "Clear result had no safe checkpoint path: $attemptLog" }
        $checkpoint = [IO.Path]::GetFullPath((Join-Path $working ($marker.Replace('/', '\'))))
        if (-not $checkpoint.StartsWith($logsRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $checkpoint -PathType Leaf)) { throw "Checkpoint was not created: $marker" }
        return [pscustomobject][ordered]@{ Checkpoint = $checkpoint; Log = $attemptLog; Attempts = $attempt; Learned = $events.Count }
    }
    if ($result -ne 2) { throw "Attempt $attempt returned unexpected result ${result}: $resultLine" }
}
throw "Developer play exhausted $Attempts attempts without a clear. Logs: $($attemptLogs -join ', ')"
