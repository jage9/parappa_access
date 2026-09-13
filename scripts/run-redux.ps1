[CmdletBinding()]
param(
    [string]$Lua,
    [string]$Bios = 'tools/pcsx-redux/openbios.bin',
    [string]$Image,
    [string]$Log = 'logs/redux.log',
    [switch]$Debugger,
    [switch]$Interactive,
    [switch]$Wait,
    [int]$DurationSeconds = 0
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if ($DurationSeconds -lt 0) {
    throw '-DurationSeconds must be zero or a positive integer.'
}

function Resolve-RepoFile([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'A required path was empty.' }
    if (-not [IO.Path]::IsPathRooted($Path)) { $Path = Join-Path $repo $Path }
    $Path = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "File not found: $Path" }
    return (Get-Item -LiteralPath $Path -ErrorAction Stop).FullName
}

function Quote-Argument([string]$Value) {
    if ($null -eq $Value) { throw 'Cannot quote a null argument.' }
    # The wrapper receives one Windows command-line string. Escape quotes and
    # trailing backslashes according to CommandLineToArgvW rules.
    $escaped = $Value -replace '(\\*)"', '$1$1\"'
    $escaped = $escaped -replace '(\\+)$', '$1$1'
    return '"' + $escaped + '"'
}

function Get-RunningRedux {
    param([string[]]$KnownPaths)

    $paths = @($KnownPaths | ForEach-Object { [IO.Path]::GetFullPath($_) })
    $running = @()
    foreach ($candidate in @(Get-Process -Name 'pcsx-redux','pcsx-redux.main' -ErrorAction SilentlyContinue)) {
        $path = $null
        try { $path = [IO.Path]::GetFullPath($candidate.Path) } catch { }
        # If the path cannot be inspected, fail closed to protect memcards.
        $sameInstall = $null -eq $path
        foreach ($known in $paths) {
            if ($null -ne $path -and [string]::Equals($path, $known, [StringComparison]::OrdinalIgnoreCase)) {
                $sameInstall = $true
            }
        }
        if ($sameInstall) {
            $running += [pscustomobject][ordered]@{
                Id = [int]$candidate.Id
                Name = $candidate.ProcessName
                Path = $path
            }
        }
    }
    return $running
}

function Get-DirectMainChild {
    param(
        [int]$ParentPid,
        [string]$MainPath,
        [DateTime]$LauncherStartUtc
    )

    $script:ChildLookupFailed = $false
    try {
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentPid" -ErrorAction Stop)
    }
    catch {
        $script:ChildLookupFailed = $true
        return $null
    }

    foreach ($row in $children) {
        if (-not [string]::Equals($row.ExecutablePath, $MainPath, [StringComparison]::OrdinalIgnoreCase)) { continue }
        try {
            $child = Get-Process -Id ([int]$row.ProcessId) -ErrorAction Stop
            $childStartUtc = $child.StartTime.ToUniversalTime()
            if ($childStartUtc -lt $LauncherStartUtc.AddSeconds(-2)) { continue }
            return [pscustomobject][ordered]@{
                Id = [int]$row.ProcessId
                StartUtc = $childStartUtc
                Path = [IO.Path]::GetFullPath($child.Path)
            }
        }
        catch {
            # Ignore a child that exited while the process list was read.
        }
    }
    return $null
}

function Stop-VerifiedProcess {
    param(
        [int]$Id,
        [string]$ExpectedPath,
        [DateTime]$ExpectedStartUtc
    )

    try {
        $process = Get-Process -Id $Id -ErrorAction Stop
        $path = [IO.Path]::GetFullPath($process.Path)
        $startUtc = $process.StartTime.ToUniversalTime()
        $sameProcess = [string]::Equals($path, [IO.Path]::GetFullPath($ExpectedPath), [StringComparison]::OrdinalIgnoreCase) -and
            ($startUtc.Ticks -eq $ExpectedStartUtc.Ticks)
        if (-not $sameProcess) {
            Write-Warning "Did not stop PID $Id because its path or start time changed."
            return
        }
        if (-not $process.HasExited) {
            $process.Kill()
            [void]$process.WaitForExit(2000)
        }
    }
    catch {
        if ($_.Exception.Message -notmatch '(?i)exited|no process') {
            Write-Warning "Could not stop launched PID ${Id}: $($_.Exception.Message)"
        }
    }
}

$exe = Resolve-RepoFile 'tools/pcsx-redux/pcsx-redux.exe'
$mainExe = Join-Path (Split-Path -Parent $exe) 'pcsx-redux.main'
$biosPath = Resolve-RepoFile $Bios
if (-not $Image) {
    $images = @(Get-ChildItem -LiteralPath (Join-Path $repo 'game') -File -ErrorAction Stop |
        Where-Object { $_.Extension -eq '.img' })
    if ($images.Count -ne 1) { throw 'Expected one IMG in game/. Use -Image to select a disc explicitly.' }
    $Image = $images[0].FullName
}
$imagePath = Resolve-RepoFile $Image
$working = Split-Path -Parent $exe
$knownPaths = @($exe, $mainExe)

$logPath = $null
if (-not [string]::IsNullOrWhiteSpace($Log)) {
    if (-not [IO.Path]::IsPathRooted($Log)) { $Log = Join-Path $repo $Log }
    $logPath = [IO.Path]::GetFullPath($Log)
    $logParent = Split-Path -Parent $logPath
    if ([string]::IsNullOrWhiteSpace($logParent)) { $logParent = $repo }
}

$existing = @(Get-RunningRedux -KnownPaths $knownPaths)
if ($existing.Count -gt 0) {
    $details = ($existing | ForEach-Object { "PID $($_.Id) ($($_.Name))" }) -join ', '
    throw "PCSX-Redux is already running for this portable installation: $details. Close it before launching another instance."
}

$arguments = @('-portable', (Quote-Argument $working), '-bios', (Quote-Argument $biosPath),
    '-iso', (Quote-Argument $imagePath), '-run', '-stdout', '-lua_stdout', '-no-trace')
if ($Debugger) { $arguments += @('-debugger', '-interpreter') }
if ($Lua) { $arguments += @('-dofile', (Quote-Argument (Resolve-RepoFile $Lua))) }
if ($DurationSeconds -gt 0) {
    $durationScript = (Resolve-RepoFile 'scripts/duration-limit.lua').Replace('\', '/')
    if ($durationScript.Contains(']]')) { throw 'Unsupported double closing bracket in repository path.' }
    $arguments += @('-exec', (Quote-Argument "Support.extra.dofile([[$durationScript]])($DurationSeconds)"))
}
if ($null -ne $logPath) {
    [IO.Directory]::CreateDirectory($logParent) | Out-Null
    $arguments += @('-logfile', (Quote-Argument $logPath))
}

# Leave stdout/stderr inherited so -stdout is visible immediately and large
# traces are not buffered in PowerShell. -lua_stdout plus -logfile keeps Lua
# lines in the durable PCSX.log-style file even when the wrapper detaches.
$info = New-Object Diagnostics.ProcessStartInfo
$info.FileName = $exe
$info.Arguments = $arguments -join ' '
$info.WorkingDirectory = $working
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.WindowStyle = if ($Interactive) { 'Normal' } else { 'Hidden' }
$info.RedirectStandardOutput = $false
$info.RedirectStandardError = $false

$process = $null
$child = $null
$launcherStartUtc = [DateTime]::UtcNow
Write-Output "Launching $exe $($info.Arguments)"
try {
    $process = [Diagnostics.Process]::Start($info)
    if (-not $process) { throw 'PCSX-Redux process could not be started.' }
    try { $launcherStartUtc = $process.StartTime.ToUniversalTime() } catch { }
    Write-Output "PCSX-Redux launcher PID=$($process.Id); log=$(if ($null -ne $logPath) { $logPath } else { '(disabled)' })"

    if ($Wait -or ($DurationSeconds -gt 0)) {
        $deadline = if ($DurationSeconds -gt 0) { [DateTime]::UtcNow.AddSeconds($DurationSeconds + 5) } else { $null }
        while (-not $process.HasExited) {
            $candidate = Get-DirectMainChild -ParentPid $process.Id -MainPath $mainExe -LauncherStartUtc $launcherStartUtc
            if ($null -ne $candidate) { $child = $candidate }
            if ($null -ne $deadline -and [DateTime]::UtcNow -ge $deadline) { break }
            Start-Sleep -Milliseconds 100
        }

        if ($null -ne $deadline -and -not $process.HasExited -and [DateTime]::UtcNow -ge $deadline) {
            # Query once more immediately before cleanup, then stop only the
            # verified direct child and wrapper created by this invocation.
            $candidate = Get-DirectMainChild -ParentPid $process.Id -MainPath $mainExe -LauncherStartUtc $launcherStartUtc
            if ($null -ne $candidate) { $child = $candidate }
            if ($null -ne $child) { Stop-VerifiedProcess -Id $child.Id -ExpectedPath $mainExe -ExpectedStartUtc $child.StartUtc }
            Stop-VerifiedProcess -Id $process.Id -ExpectedPath $exe -ExpectedStartUtc $launcherStartUtc
            if ($script:ChildLookupFailed) {
                Write-Warning 'Could not query the wrapper child through Win32_Process; only the wrapper was verified for cleanup.'
            }
            throw 'Emulator did not honor the Lua duration limit. Verified processes were stopped; inspect the log and any child-query warning.'
        }

        if ($null -ne $process -and -not $process.HasExited) {
            try { [void]$process.WaitForExit(2000) } catch { }
        }
        if (-not ($null -ne $deadline -and [DateTime]::UtcNow -ge $deadline)) {
            if ($process.ExitCode -ne 0) { throw "PCSX-Redux exited with code $($process.ExitCode). See $logPath" }
        }
    }
}
catch {
    if ($null -ne $process) {
        $candidate = Get-DirectMainChild -ParentPid $process.Id -MainPath $mainExe -LauncherStartUtc $launcherStartUtc
        if ($null -ne $candidate) { $child = $candidate }
        if ($null -ne $child) { Stop-VerifiedProcess -Id $child.Id -ExpectedPath $mainExe -ExpectedStartUtc $child.StartUtc }
        Stop-VerifiedProcess -Id $process.Id -ExpectedPath $exe -ExpectedStartUtc $launcherStartUtc
    }
    throw
}

# The Windows bootstrapper does not reliably forward the main executable's
# console streams. Give bounded runs useful textual results regardless.
if (($Wait -or $DurationSeconds -gt 0) -and $logPath -and (Test-Path -LiteralPath $logPath)) {
    Get-Content -LiteralPath $logPath -Tail 200
}
