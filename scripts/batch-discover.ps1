# ============================================================
# batch-discover.ps1 — 从面经专区批量发现 + 处理
# 用法: .\scripts\batch-discover.ps1          (扫 1 页)
#       .\scripts\batch-discover.ps1 -Pages 3  (扫 3 页)
# ============================================================
param (
    [int]$Pages = 1
)

$env:Path = "C:\Users\Joker\.local\bin;$env:Path"

Write-Host "=== [1/3] 批量发现 + 抓取 ($Pages 页) ==="
uv run il batch --pages $Pages --inline

Write-Host ""
Write-Host "=== [2/3] Embedding 回填 ==="
uv run il backfill-embeddings

Write-Host ""
Write-Host "=== [3/3] 聚合摘要 ==="
uv run il aggregate

Write-Host ""
Write-Host "=== 完成 → 刷新 http://localhost:3000 ==="
