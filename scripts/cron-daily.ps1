# ============================================================
# cron-daily.ps1 — 增量更新：发现新帖 + 补全 AI 管线
# 适用场景：Windows 任务计划程序每天定时跑
# 用法: .\scripts\cron-daily.ps1
#       .\scripts\cron-daily.ps1 -Pages 2
# ============================================================
param([int]$Pages = 1)

$env:Path = "C:\Users\Joker\.local\bin;$env:Path"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "=== [$(Get-Date -Format 'yyyy-MM-dd HH:mm')] Incremental crawl start ===" -ForegroundColor Cyan

# 1. 发现新帖（已存在的自动跳过，不重复下载）
Write-Host "[1/3] Discovering new posts ..." -ForegroundColor Yellow
uv run il batch --pages $Pages --source interview --inline
if ($LASTEXITCODE -ne 0) {
    Write-Host "batch failed, stopping" -ForegroundColor Red
    exit 1
}

# 2. 只处理 pending 状态的帖子（新发现的 + 之前失败的）
Write-Host "[2/3] Extracting pending posts ..." -ForegroundColor Yellow
uv run il resume
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 3) {
    Write-Host "resume had errors (some posts may need attention)" -ForegroundColor Yellow
}

# 3. 更新 embeddings + 聚合
Write-Host "[3/3] Rebuilding embeddings & summaries ..." -ForegroundColor Yellow
uv run il backfill-embeddings
uv run il aggregate

Write-Host "=== [$(Get-Date -Format 'yyyy-MM-dd HH:mm')] Incremental crawl done ===" -ForegroundColor Green
