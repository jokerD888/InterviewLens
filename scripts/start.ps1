# ============================================================
# start.ps1 — 一键启动 InterviewLens 全栈服务
# 用法: .\scripts\start.ps1
#       .\scripts\start.ps1 -NoFrontend   (只启动后端+数据库)
# ============================================================
param([switch]$NoFrontend)

$env:Path = "C:\Users\Joker\.local\bin;$env:Path"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  InterviewLens · 一键启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---- Docker ----
Write-Host "[1/3] 启动 Docker 服务 (PostgreSQL + Redis + Langfuse) ..." -ForegroundColor Yellow
cd $root
docker compose up -d 2>&1 | Out-Null
Write-Host "       Docker 已启动" -ForegroundColor Green

# ---- Backend ----
Write-Host ""
Write-Host "[2/3] 启动后端 API (FastAPI) ..." -ForegroundColor Yellow
$backendJob = Start-Process -FilePath "C:\Users\Joker\.local\bin\uv.exe" `
    -ArgumentList "run", "il", "serve" `
    -WorkingDirectory $root `
    -WindowStyle Minimized `
    -PassThru
Write-Host "       后端 PID: $($backendJob.Id)  →  http://localhost:8000" -ForegroundColor Green

if (-not $NoFrontend) {
    Write-Host ""
    Write-Host "[3/3] 启动前端 (Next.js) ..." -ForegroundColor Yellow
    if (Test-Path "$root\web\node_modules") {
        $frontendJob = Start-Process -FilePath "pnpm" `
            -ArgumentList "dev" `
            -WorkingDirectory "$root\web" `
            -WindowStyle Minimized `
            -PassThru
        Write-Host "       前端 PID: $($frontendJob.Id)  →  http://localhost:3000" -ForegroundColor Green
    } else {
        Write-Host "       前端依赖未安装，请先运行: cd web && pnpm install" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  后端:  http://localhost:8000/docs" -ForegroundColor White
if (-not $NoFrontend) {
    Write-Host "  前端:  http://localhost:3000" -ForegroundColor White
}
Write-Host "  数据库: localhost:5433  Redis: localhost:6380" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
