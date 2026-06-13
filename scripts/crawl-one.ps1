# ============================================================
# crawl-one.ps1 <url> — 抓取 + 全流水线一条龙
# 用法: .\scripts\crawl-one.ps1 "https://www.nowcoder.com/feed/main/detail/xxxxx"
# ============================================================
param (
    [Parameter(Mandatory=$true)]
    [string]$Url
)

$env:Path = "C:\Users\Joker\.local\bin;$env:Path"

Write-Host "=== [1/3] 抓取 + 抽取 + 归一 + 打分 ==="
uv run il graph $Url

Write-Host ""
Write-Host "=== [2/3] Embedding 回填 ==="
uv run il backfill-embeddings

Write-Host ""
Write-Host "=== [3/3] 聚合摘要 ==="
uv run il aggregate

Write-Host ""
Write-Host "=== 完成 → 刷新 http://localhost:3000 ==="
