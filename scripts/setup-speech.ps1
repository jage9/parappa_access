[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$target = Join-Path $repo 'tools/prism-python'
& python -m pip install --disable-pip-version-check --only-binary=:all: --upgrade --target $target prismatoid==0.18.2 cffi==2.1.1 pycparser==3.0
if ($LASTEXITCODE -ne 0) { throw 'Prism installation failed.' }
# pip's temporary-directory ACL can otherwise exclude the desktop user when
# installation runs in the Codex sandbox. Inherit the repository's own ACL.
& icacls $target /inheritance:e /T /C /Q
if ($LASTEXITCODE -ne 0) { throw 'Could not restore inherited package permissions.' }
Write-Output 'Prism installed locally. Run accessible-menu.ps1 -SpeechTest to check speech.'
