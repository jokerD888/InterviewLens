# ============================================================
# rebuild.ps1 — 对已有帖子重跑 embeddings + 聚合（Prompt 调优后刷新）
# 用法: .\scripts\rebuild.ps1
# ============================================================
$env:Path = "C:\Users\Joker\.local\bin;$env:Path"

Write-Host "=== [1/2] Embedding 回填 ==="
uv run il backfill-embeddings

Write-Host ""
Write-Host "=== [2/2] 聚合摘要 ==="
uv run il aggregate

Write-Host ""
Write-Host "=== 完成 → 刷新 http://localhost:3000 ==="
