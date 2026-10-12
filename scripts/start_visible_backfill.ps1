param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeConfig = 'D:\tmp\InterviewLensRuntime\runtime-env.ps1',
    [switch]$Once
)
$ErrorActionPreference = 'Stop'
$taskCodeRoot = Split-Path -Parent $PSScriptRoot
. $RuntimeConfig
Set-Location -LiteralPath $ProjectRoot
$env:PYTHONPATH = Join-Path $taskCodeRoot 'src'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$Host.UI.RawUI.WindowTitle = 'InterviewLens - visible backfill'
$taskArguments = @((Join-Path $taskCodeRoot 'scripts\visible_backfill.py'), '--project-root', $ProjectRoot)
if ($Once) { $taskArguments += '--once' }
& $runtimePython @taskArguments
Write-Host "Crawler exited with code $LASTEXITCODE. The window remains open."
