[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$ImagePath,
    [string]$CcdPath,
    [string]$EmulatorDirectory,
    [switch]$AsJson
)

# Read-only inspection of the local CloneCD image and PCSX-Redux/OpenBIOS
# artifacts.  The script deliberately reads the image in place and never
# extracts, rewrites, or copies disc or BIOS data.

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = [IO.Path]::GetFullPath((Join-Path -Path $PSScriptRoot -ChildPath '..'))
}
else {
    $RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
}

if ([string]::IsNullOrWhiteSpace($ImagePath)) {
    $imageCandidates = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'game') -Filter '*.img' -File -ErrorAction Stop)
    if ($imageCandidates.Count -ne 1) {
        throw "Expected exactly one .img under '$RepoRoot\game'; found $($imageCandidates.Count). Pass -ImagePath explicitly."
    }
    $ImagePath = $imageCandidates[0].FullName
}
else {
    $ImagePath = [IO.Path]::GetFullPath($ImagePath)
}

if ([string]::IsNullOrWhiteSpace($CcdPath)) {
    $ccdCandidates = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'game') -Filter '*.ccd' -File -ErrorAction Stop)
    if ($ccdCandidates.Count -ne 1) {
        throw "Expected exactly one .ccd under '$RepoRoot\game'; found $($ccdCandidates.Count). Pass -CcdPath explicitly."
    }
    $CcdPath = $ccdCandidates[0].FullName
}
else {
    $CcdPath = [IO.Path]::GetFullPath($CcdPath)
}

if ([string]::IsNullOrWhiteSpace($EmulatorDirectory)) {
    $EmulatorDirectory = Join-Path $RepoRoot 'tools\pcsx-redux'
}
else {
    $EmulatorDirectory = [IO.Path]::GetFullPath($EmulatorDirectory)
}

foreach ($requiredPath in @($ImagePath, $CcdPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file does not exist: $requiredPath"
    }
}

function Get-TextField {
    param(
        [byte[]]$Bytes,
        [int]$Offset,
        [int]$Length
    )

    $value = [Text.Encoding]::ASCII.GetString($Bytes, $Offset, $Length)
    return ($value -replace "^[\x00 ]+", '' -replace "[\x00 ]+$", '')
}

function Get-UInt16LE {
    param([byte[]]$Bytes, [int]$Offset)
    return [BitConverter]::ToUInt16($Bytes, $Offset)
}

function Get-UInt32LE {
    param([byte[]]$Bytes, [int]$Offset)
    return [BitConverter]::ToUInt32($Bytes, $Offset)
}

function Convert-CcdInteger {
    param([string]$Value)

    $trimmed = $Value.Trim()
    if ($trimmed -match '^[-+]?0x[0-9a-fA-F]+$') {
        $negative = $trimmed.StartsWith('-')
        $hex = $trimmed.TrimStart('-', '+').Substring(2)
        $number = [Convert]::ToInt64($hex, 16)
        if ($negative) { return -$number }
        return $number
    }
    return [Int64]$trimmed
}

function Read-CloneCd {
    param([string]$Path)

    $sections = [ordered]@{}
    $current = $null
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        $text = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($text) -or $text.StartsWith(';')) { continue }

        if ($text -match '^\[(?<name>[^]]+)\]$') {
            $current = $Matches['name']
            $sections[$current] = [ordered]@{}
            continue
        }

        if ($null -ne $current -and $text -match '^(?<key>[^=]+)=(?<value>.*)$') {
            $sections[$current][$Matches['key'].Trim()] = $Matches['value'].Trim()
        }
    }

    $tocEntries = @()
    foreach ($name in $sections.Keys) {
        if ($name -notmatch '^Entry ') { continue }
        $entry = $sections[$name]
        $point = Convert-CcdInteger $entry['Point']
        $tocEntries += [pscustomobject][ordered]@{
            Entry = [int](Convert-CcdInteger $name.Substring(6))
            Point = ('0x{0:X2}' -f $point)
            PointValue = $point
            TrackNo = [int](Convert-CcdInteger $entry['TrackNo'])
            Control = ('0x{0:X2}' -f (Convert-CcdInteger $entry['Control']))
            Adr = ('0x{0:X2}' -f (Convert-CcdInteger $entry['ADR']))
            AlBa = [int64](Convert-CcdInteger $entry['ALBA'])
            PlBa = [int64](Convert-CcdInteger $entry['PLBA'])
            Position = ('{0:D2}:{1:D2}:{2:D2}' -f
                (Convert-CcdInteger $entry['PMin']),
                (Convert-CcdInteger $entry['PSec']),
                (Convert-CcdInteger $entry['PFrame']))
        }
    }

    $tracks = @()
    foreach ($name in $sections.Keys) {
        if ($name -notmatch '^TRACK (?<number>\d+)$') { continue }
        $number = [int]$Matches['number']
        $track = $sections[$name]
        $entry = $tocEntries | Where-Object { $_.PointValue -eq $number } | Select-Object -First 1
        $tracks += [pscustomobject][ordered]@{
            Number = $number
            Mode = [int](Convert-CcdInteger $track['MODE'])
            Index1 = [int64](Convert-CcdInteger $track['INDEX 1'])
            Control = if ($null -ne $entry) { $entry.Control } else { $null }
            StartLba = if ($null -ne $entry) { $entry.PlBa } else { $null }
            Sectors = $null
        }
    }

    $leadOut = $tocEntries | Where-Object { $_.PointValue -eq 0xA2 } | Select-Object -First 1
    foreach ($track in $tracks) {
        if ($null -ne $leadOut -and $null -ne $track.StartLba) {
            $track.Sectors = $leadOut.PlBa - $track.StartLba
        }
    }

    $session = $sections['Session 1']
    [pscustomobject][ordered]@{
        Version = if ($sections.Contains('CloneCD')) { $sections['CloneCD']['Version'] } else { $null }
        TocEntries = if ($sections.Contains('Disc')) { [int](Convert-CcdInteger $sections['Disc']['TocEntries']) } else { $null }
        Sessions = if ($sections.Contains('Disc')) { [int](Convert-CcdInteger $sections['Disc']['Sessions']) } else { $null }
        DataTracksScrambled = if ($sections.Contains('Disc')) { [int](Convert-CcdInteger $sections['Disc']['DataTracksScrambled']) } else { $null }
        Session = if ($null -ne $session) {
            [pscustomobject][ordered]@{
                PreGapMode = [int](Convert-CcdInteger $session['PreGapMode'])
                PreGapSubC = [int](Convert-CcdInteger $session['PreGapSubC'])
            }
        } else { $null }
        Entries = @($tocEntries | Sort-Object Entry)
        Tracks = @($tracks | Sort-Object Number)
    }
}

$script:DiscStream = $null
$script:RawSectorSize = 2352
$script:UserDataOffset = $null
$script:UserDataSize = 2048

function Read-RawBytes {
    param([long]$Offset, [int]$Count)

    if ($Offset -lt 0 -or $Count -lt 0) { throw "Invalid image read offset/count: $Offset/$Count" }
    $bytes = New-Object byte[] $Count
    [void]$script:DiscStream.Seek($Offset, [IO.SeekOrigin]::Begin)
    $read = 0
    while ($read -lt $Count) {
        $n = $script:DiscStream.Read($bytes, $read, $Count - $read)
        if ($n -le 0) { throw "Unexpected end of image at byte offset $($Offset + $read)." }
        $read += $n
    }
    return $bytes
}

function Read-UserBytes {
    param([long]$Offset, [int]$Count)

    if ($null -eq $script:UserDataOffset) { throw 'ISO user-data offset has not been detected.' }
    if ($Offset -lt 0 -or $Count -lt 0) { throw "Invalid ISO read offset/count: $Offset/$Count" }
    $bytes = New-Object byte[] $Count
    $done = 0
    while ($done -lt $Count) {
        $absoluteUserOffset = $Offset + $done
        $lba = [math]::Floor($absoluteUserOffset / $script:UserDataSize)
        $withinSector = [int]($absoluteUserOffset % $script:UserDataSize)
        $take = [math]::Min($Count - $done, $script:UserDataSize - $withinSector)
        $rawOffset = ([int64]$lba * $script:RawSectorSize) + $script:UserDataOffset + $withinSector
        $chunk = Read-RawBytes -Offset $rawOffset -Count $take
        [Array]::Copy($chunk, 0, $bytes, $done, $take)
        $done += $take
    }
    return $bytes
}

function Read-IsoDirectory {
    param([byte[]]$Bytes)

    $entries = @()
    $position = 0
    while ($position -lt $Bytes.Length) {
        $length = $Bytes[$position]
        if ($length -eq 0) {
            $position = (([math]::Floor($position / $script:UserDataSize) + 1) * $script:UserDataSize)
            continue
        }
        if ($length -lt 34 -or ($position + $length) -gt $Bytes.Length) {
            throw "Invalid ISO9660 directory record at byte offset $position (length $length)."
        }

        $identifierLength = $Bytes[$position + 32]
        if (33 + $identifierLength -gt $length) {
            throw "Invalid ISO9660 directory identifier at byte offset $position."
        }
        if ($identifierLength -eq 1 -and $Bytes[$position + 33] -eq 0) {
            $identifier = '.'
        }
        elseif ($identifierLength -eq 1 -and $Bytes[$position + 33] -eq 1) {
            $identifier = '..'
        }
        else {
            $identifier = [Text.Encoding]::ASCII.GetString($Bytes, $position + 33, $identifierLength)
        }
        $entries += [pscustomobject][ordered]@{
            Name = $identifier
            NameWithoutVersion = ($identifier -replace ';[0-9]+$', '')
            IsDirectory = (($Bytes[$position + 25] -band 0x02) -ne 0)
            ExtentLba = [int64](Get-UInt32LE -Bytes $Bytes -Offset ($position + 2))
            DataLength = [int64](Get-UInt32LE -Bytes $Bytes -Offset ($position + 10))
            Flags = $Bytes[$position + 25]
            RecordLength = $length
        }
        $position += $length
    }
    return $entries
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Get-FileMetadata {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    [pscustomobject][ordered]@{
        Name = $item.Name
        SizeBytes = [int64]$item.Length
        SHA256 = Get-FileSha256 -Path $item.FullName
    }
}

$ccd = Read-CloneCd -Path $CcdPath
$gameFiles = @(Get-ChildItem -LiteralPath (Split-Path -Parent $ImagePath) -File |
    Where-Object { $_.Extension.ToLowerInvariant() -in @('.ccd', '.img', '.sub') } |
    Sort-Object Name |
    ForEach-Object { Get-FileMetadata -Path $_.FullName })

$script:DiscStream = [IO.File]::Open($ImagePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
try {
    $imageLength = $script:DiscStream.Length
    if (($imageLength % $script:RawSectorSize) -ne 0) {
        throw "IMG length $imageLength is not an integer number of $($script:RawSectorSize)-byte sectors."
    }
    $sectorCount = [int64]($imageLength / $script:RawSectorSize)

    $sector0 = Read-RawBytes -Offset 0 -Count $script:RawSectorSize
    $mode = $sector0[15]
    if ($mode -eq 2) { $script:UserDataOffset = 24 }
    elseif ($mode -eq 1) { $script:UserDataOffset = 16 }
    else { throw "Unsupported first-sector mode byte: $mode" }

    $pvd = Read-UserBytes -Offset (16 * $script:UserDataSize) -Count $script:UserDataSize
    if ($pvd[0] -ne 1 -or (Get-TextField -Bytes $pvd -Offset 1 -Length 5) -ne 'CD001') {
        throw 'ISO9660 primary volume descriptor was not found at LBA 16.'
    }

    $rootOffset = 156
    $rootRecordLength = $pvd[$rootOffset]
    if ($rootRecordLength -lt 34) { throw 'ISO9660 root directory record is invalid.' }
    $rootExtent = [int64](Get-UInt32LE -Bytes $pvd -Offset ($rootOffset + 2))
    $rootLength = [int64](Get-UInt32LE -Bytes $pvd -Offset ($rootOffset + 10))
    $rootBytes = Read-UserBytes -Offset ($rootExtent * $script:UserDataSize) -Count ([int]$rootLength)
    $rootEntries = @(Read-IsoDirectory -Bytes $rootBytes)

    $systemEntry = $rootEntries | Where-Object { $_.NameWithoutVersion.ToUpperInvariant() -eq 'SYSTEM.CNF' } | Select-Object -First 1
    $systemText = $null
    $bootPath = $null
    $executableName = $null
    if ($null -ne $systemEntry) {
        if ($systemEntry.DataLength -gt 65536) { throw 'SYSTEM.CNF is unexpectedly large; refusing to read it.' }
        $systemBytes = Read-UserBytes -Offset ($systemEntry.ExtentLba * $script:UserDataSize) -Count ([int]$systemEntry.DataLength)
        $systemText = [Text.Encoding]::ASCII.GetString($systemBytes).Trim([char]0, [char]13, [char]10, [char]32, [char]9)
        $bootMatch = [regex]::Match($systemText, '(?im)^\s*BOOT\s*=\s*(?<path>[^\s]+)')
        if ($bootMatch.Success) {
            $bootPath = $bootMatch.Groups['path'].Value
            $bootName = ($bootPath -replace '^.*[\\/]', '')
            $matchingExecutable = $rootEntries |
                Where-Object { $_.NameWithoutVersion.ToUpperInvariant() -eq ($bootName -replace ';[0-9]+$', '').ToUpperInvariant() } |
                Select-Object -First 1
            if ($null -ne $matchingExecutable) {
                $executableName = $matchingExecutable.Name
            }
            else {
                $executableName = $bootName
            }
        }
    }

    $volumeSpace = [int64](Get-UInt32LE -Bytes $pvd -Offset 80)
    $logicalBlockSize = [int](Get-UInt16LE -Bytes $pvd -Offset 128)
    $volumeIdentifier = Get-TextField -Bytes $pvd -Offset 40 -Length 32
    $systemIdentifier = Get-TextField -Bytes $pvd -Offset 8 -Length 32
    $applicationIdentifier = Get-TextField -Bytes $pvd -Offset 574 -Length 128

    $serial = $null
    if ($null -ne $executableName) {
        $serial = ((($executableName -replace ';[0-9]+$', '') -replace '_', '-' -replace '\.', '').ToUpperInvariant())
    }

    $iso = [pscustomobject][ordered]@{
        SectorSizeBytes = $script:RawSectorSize
        UserDataOffsetBytes = $script:UserDataOffset
        SectorCount = $sectorCount
        PvdLba = 16
        PvdVersion = $pvd[6]
        VolumeIdentifier = $volumeIdentifier
        SystemIdentifier = $systemIdentifier
        ApplicationIdentifier = $applicationIdentifier
        VolumeSpaceSize = $volumeSpace
        LogicalBlockSize = $logicalBlockSize
        RootDirectoryExtentLba = $rootExtent
        RootDirectoryDataLength = $rootLength
        RootEntries = $rootEntries
        SystemCnf = if ($null -ne $systemEntry) {
            [pscustomobject][ordered]@{
                Name = $systemEntry.Name
                ExtentLba = $systemEntry.ExtentLba
                DataLength = $systemEntry.DataLength
                BootPath = $bootPath
            }
        } else { $null }
        ExecutableFilename = $executableName
        DiscSerial = $serial
    }
}
finally {
    if ($null -ne $script:DiscStream) {
        $script:DiscStream.Dispose()
        $script:DiscStream = $null
    }
}

$versionPath = Join-Path $EmulatorDirectory 'version.json'
$version = $null
if (Test-Path -LiteralPath $versionPath -PathType Leaf) {
    $version = Get-Content -Raw -LiteralPath $versionPath | ConvertFrom-Json
}

$emulatorFiles = @()
foreach ($name in @('pcsx-redux.exe', 'pcsx-redux.main')) {
    $path = Join-Path $EmulatorDirectory $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $emulatorFiles += Get-FileMetadata -Path $path
    }
}

$openBiosFiles = @(Get-ChildItem -LiteralPath $EmulatorDirectory -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '(?i)^openbios.*\.(bin|elf|rom)$' } |
    Sort-Object Name |
    ForEach-Object { Get-FileMetadata -Path $_.FullName })

$report = [pscustomobject][ordered]@{
    GeneratedUtc = [DateTime]::UtcNow.ToString('o')
    GameFiles = $gameFiles
    Ccd = $ccd
    Iso9660 = $iso
    Emulator = [pscustomobject][ordered]@{
        Directory = $EmulatorDirectory
        Version = $version
        Files = $emulatorFiles
        OpenBiosFiles = $openBiosFiles
        DefaultOpenBios = ($openBiosFiles | Where-Object { $_.Name -eq 'openbios.bin' } | Select-Object -First 1)
    }
}

if ($AsJson) {
    $report | ConvertTo-Json -Depth 8
    exit 0
}

Write-Output '# Disc metadata'
Write-Output ''
Write-Output "Image: $($gameFiles | Where-Object { $_.Name -eq (Split-Path -Leaf $ImagePath) } | Select-Object -ExpandProperty Name)"
Write-Output "Disc serial: $($iso.DiscSerial)"
Write-Output "Executable: $($iso.ExecutableFilename)"
Write-Output "ISO volume identifier: $($iso.VolumeIdentifier)"
Write-Output "ISO system identifier: $($iso.SystemIdentifier)"
Write-Output "Raw sector layout: $($iso.SectorCount) x $($iso.SectorSizeBytes)-byte sectors; ISO user data offset $($iso.UserDataOffsetBytes)"
Write-Output ''
Write-Output '## CloneCD layout'
Write-Output ''
Write-Output "Version $($ccd.Version); $($ccd.Sessions) session(s); $($ccd.TocEntries) TOC entries; scrambled=$($ccd.DataTracksScrambled)."
if ($null -ne $ccd.Session) {
    Write-Output "Session 1 pregap mode=$($ccd.Session.PreGapMode), subchannel=$($ccd.Session.PreGapSubC)."
}
foreach ($track in $ccd.Tracks) {
    $audio = if ($track.Control -eq '0x00') { 'audio' } else { 'data' }
    Write-Output "Track $($track.Number): MODE $($track.Mode), $audio, index 1=$($track.Index1), start LBA=$($track.StartLba), sectors=$($track.Sectors)."
}
Write-Output ''
Write-Output '## ISO9660 root'
Write-Output ''
Write-Output "PVD LBA=$($iso.PvdLba), version=$($iso.PvdVersion), volume blocks=$($iso.VolumeSpaceSize), logical block size=$($iso.LogicalBlockSize)."
Write-Output "Root directory extent LBA=$($iso.RootDirectoryExtentLba), bytes=$($iso.RootDirectoryDataLength)."
Write-Output ('Root entries: ' + (($iso.RootEntries | ForEach-Object { $_.Name }) -join ', '))
if ($null -ne $iso.SystemCnf) {
    Write-Output "SYSTEM.CNF=$($iso.SystemCnf.Name), extent LBA=$($iso.SystemCnf.ExtentLba), bytes=$($iso.SystemCnf.DataLength), BOOT=$($iso.SystemCnf.BootPath)."
}
Write-Output ''
Write-Output '## File hashes'
Write-Output ''
foreach ($file in $gameFiles) { Write-Output "- $($file.Name): $($file.SizeBytes) bytes, SHA-256 $($file.SHA256)" }
foreach ($file in $openBiosFiles) { Write-Output "- $($file.Name): $($file.SizeBytes) bytes, SHA-256 $($file.SHA256)" }
if ($null -ne $version) {
    Write-Output "- PCSX-Redux build: version=$($version.version), buildId=$($version.buildId), changeset=$($version.changeset), channel=$($version.channel)"
}
