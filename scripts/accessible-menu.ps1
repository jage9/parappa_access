[CmdletBinding()]
param([switch]$NoSpeech, [switch]$SpeechTest, [switch]$DeveloperMenu, [switch]$ConsoleMenu)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'accessible-menu.py'))
if ($NoSpeech) { $arguments += '--no-speech' }
if ($SpeechTest) { $arguments += '--speech-test' }
if ($DeveloperMenu) { $arguments += '--developer-menu' }
if ($ConsoleMenu) { $arguments += '--console-menu' }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Accessible menu failed. See the message above.' }
