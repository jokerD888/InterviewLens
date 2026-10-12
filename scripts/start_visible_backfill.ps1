param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeConfig = 'D:\tmp\InterviewLensRuntime\runtime-env.ps1',
    [switch]$Once,
    [ValidateSet('tab','job')][string]$Listing = 'tab',
    [int]$JobId = -1,
    [ValidateRange(1,3)][int]$JobLevel = 1,
    [string]$Since,
    [switch]$Partitioned
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
$taskArguments += @('--listing', $Listing, '--job-id', "$JobId", '--job-level', "$JobLevel")
if ($Since) { $taskArguments += @('--since', $Since) }
if ($Partitioned) { $taskArguments += '--partitioned' }
if ($Once) { $taskArguments += '--once' }
& $runtimePython @taskArguments
Write-Host "Crawler exited with code $LASTEXITCODE. The window remains open."
