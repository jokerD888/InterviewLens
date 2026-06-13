# ============================================================
# setup-scheduler.ps1 — 创建 Windows 定时任务，每天凌晨 3 点增量抓取
# 用法（管理员 PowerShell）: .\scripts\setup-scheduler.ps1
# ============================================================
$root = Split-Path -Parent $PSScriptRoot
$scriptPath = "$root\scripts\cron-daily.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""

$trigger = New-ScheduledTaskTrigger -Daily -At 3am

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask `
    -TaskName "InterviewLens Daily Crawl" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Daily incremental crawl from Nowcoder interview zone" `
    -Force

Write-Host "Task 'InterviewLens Daily Crawl' created (daily at 3:00 AM)" -ForegroundColor Green
Write-Host "View: taskschd.msc → InterviewLens Daily Crawl" -ForegroundColor Cyan
