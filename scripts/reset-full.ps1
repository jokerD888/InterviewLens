# ============================================================
# reset-full.ps1 — 硬重置：清空一切（包括爬取的帖子）
# 适用场景：从头开始，彻底重来
# 用法: .\scripts\reset-full.ps1
# ============================================================
$env:Path = "C:\Users\Joker\.local\bin;$env:Path"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "=== WARNING: This will delete ALL posts and AI results ===" -ForegroundColor Red
Write-Host "=== Press Ctrl+C within 3 seconds to cancel ===" -ForegroundColor Red
Start-Sleep -Seconds 3

Write-Host "=== Full reset (nuke everything) ===" -ForegroundColor Yellow

$pyScript = @"
import asyncio
from sqlalchemy import text
from interviewlens.db import session_scope

async def reset():
    async with session_scope() as s:
        await s.execute(text("DELETE FROM questions"))
        await s.execute(text("DELETE FROM post_company_position"))
        await s.execute(text("DELETE FROM summaries"))
        await s.execute(text("DELETE FROM posts"))
        await s.execute(text("DELETE FROM alias_dict"))
        await s.execute(text("ALTER SEQUENCE posts_id_seq RESTART WITH 1"))
        await s.execute(text("ALTER SEQUENCE questions_id_seq RESTART WITH 1"))
        await s.execute(text("ALTER SEQUENCE summaries_id_seq RESTART WITH 1"))
        await s.execute(text("ALTER SEQUENCE alias_dict_id_seq RESTART WITH 1"))
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
Write-Host "=== Done. Database is clean. ===" -ForegroundColor Green
