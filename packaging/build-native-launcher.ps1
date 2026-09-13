$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$build = Join-Path $root 'build'
$output = Join-Path $build 'native-launcher.exe'
New-Item -ItemType Directory -Path $build -Force | Out-Null

$compiler = Get-Command cl.exe -ErrorAction SilentlyContinue
if (-not $compiler) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) {
        throw 'MSVC was not found. Install Visual Studio Build Tools with the C++ desktop workload.'
    }

    $installation = (& $vswhere -latest -products '*' `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath | Select-Object -First 1)
    if (-not $installation) {
        throw 'Visual Studio Build Tools with the x64 C++ compiler were not found.'
    }
    $devCommand = Join-Path $installation.Trim() 'Common7\Tools\VsDevCmd.bat'
    if (-not (Test-Path -LiteralPath $devCommand)) {
        throw "Visual Studio developer environment was not found: $devCommand"
    }

    $command = 'call "{0}" -no_logo -arch=x64 -host_arch=x64 >nul && set' -f $devCommand
    $environment = & $env:ComSpec /d /c $command
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not initialize the Visual Studio x64 build environment.'
    }
    $visualStudioPath = $environment |
        Where-Object { $_ -cmatch '^PATH=' } |
        Select-Object -First 1
    foreach ($entry in $environment) {
        $separator = $entry.IndexOf('=')
        if ($separator -gt 0 -and $entry.Substring(0, $separator) -ine 'Path') {
            [Environment]::SetEnvironmentVariable(
                $entry.Substring(0, $separator),
                $entry.Substring($separator + 1),
                [EnvironmentVariableTarget]::Process)
        }
    }
    if ($visualStudioPath) {
        $env:Path = $visualStudioPath.Substring(5)
    }
    $compiler = Get-Command cl.exe -ErrorAction SilentlyContinue
    if (-not $compiler) {
        throw 'The Visual Studio environment did not provide cl.exe.'
    }
}

Push-Location $root
try {
    & $compiler.Source /nologo /O1 /GS /Zl /W4 /DUNICODE /D_UNICODE `
        'packaging\native-launcher.c' '/Febuild\native-launcher.exe' `
        '/Fobuild\native-launcher.obj' /link /NODEFAULTLIB `
        /ENTRY:launcher_entry /SUBSYSTEM:WINDOWS /OPT:REF /OPT:ICF `
        /INCREMENTAL:NO shell32.lib user32.lib kernel32.lib
    if ($LASTEXITCODE -ne 0) {
        throw "Native launcher compilation failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

$result = Get-Item -LiteralPath $output
Write-Output ("Built {0} ({1:N0} bytes)" -f $result.FullName, $result.Length)
