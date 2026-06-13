# ============================================================
# reset.ps1 — 软重置：保留已爬取的帖子，清空 AI 处理结果
# 适用场景：调 prompt / 换模型后，基于已有帖子重新跑 AI 管线
# 用法: .\scripts\reset.ps1
# ============================================================
$env:Path = "C:\Users\Joker\.local\bin;$env:Path"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "=== Soft reset (keep crawled posts, reset AI results) ===" -ForegroundColor Yellow

$pyScript = @"
import asyncio
from sqlalchemy import text, update
from interviewlens.db import session_scope, Post

async def reset():
    async with session_scope() as s:
        # 清空 AI 处理结果
        await s.execute(text("DELETE FROM questions"))
        await s.execute(text("DELETE FROM summaries"))
        await s.execute(text("DELETE FROM alias_dict"))
        await s.execute(text("ALTER SEQUENCE questions_id_seq RESTART WITH 1"))
        await s.execute(text("ALTER SEQUENCE summaries_id_seq RESTART WITH 1"))
        await s.execute(text("ALTER SEQUENCE alias_dict_id_seq RESTART WITH 1"))
        # 重置帖子状态为待处理（保留 raw_html / cleaned_text）
        await s.execute(
            update(Post)
            .values(extract_status='pending', extract_error=None, extract_version=0, quality_score=None)
        )
        await s.commit()
    print("done")

asyncio.run(reset())
"@

$tmpFile = "$root/_reset_tmp.py"
$pyScript | Out-File -FilePath $tmpFile -Encoding utf8
uv run python $tmpFile
Remove-Item $tmpFile -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== Re-seeding aliases ==="
uv run il seed-aliases

Write-Host ""
Write-Host "=== Done. Run: uv run il resume    (re-extract all posts)" -ForegroundColor Green
Write-Host "===       uv run il backfill-embeddings" -ForegroundColor Green
Write-Host "===       uv run il aggregate" -ForegroundColor Green
