"""/api/bridge — export selected questions + answers to daily-interview-prep."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..answerer import generate_one
from ..config import settings
from ..db import session_scope
from ..logging import log
from .schemas import (
    BridgeExportRequest,
    BridgeExportResponse,
    BridgeGeneratedAnswer,
    BridgeGenerateRequest,
    BridgeGenerateResponse,
)
from .security import require_admin

router = APIRouter(dependencies=[Depends(require_admin)], prefix="/bridge", tags=["bridge"])


@router.post("/generate-answers", response_model=BridgeGenerateResponse)
async def generate_answers(req: BridgeGenerateRequest) -> BridgeGenerateResponse:
    """Generate AI answers for selected questions. One DeepSeek call per question."""
    results: list[BridgeGeneratedAnswer] = []

    async with session_scope() as session:
        from sqlalchemy import text as sa_text

        sql = sa_text(
            "SELECT id, content, category, answer_ai, answer_ai_version FROM questions WHERE id = ANY(:ids)"
        )
        rows = (await session.execute(sql, {"ids": req.question_ids})).all()
        qmap = {
            r[0]: {"content": r[1], "category": r[2], "answer": r[3], "version": r[4]} for r in rows
        }

    for qid in dict.fromkeys(req.question_ids):
        q = qmap.get(qid)
        if q is None:
            results.append(
                BridgeGeneratedAnswer(
                    question_id=qid,
                    content="(unknown)",
                    error="question not found",
                )
            )
            continue
        from ..llm.budget import LLMLimitError

        answer = (
            q["answer"]
            if q["version"] >= settings.answer_prompt_version and not req.regenerate
            else None
        )
        if not answer:
            try:
                answer = await generate_one(content=q["content"], category=q["category"])
            except LLMLimitError as exc:
                raise HTTPException(429, str(exc)) from exc
        if answer is None:
            results.append(
                BridgeGeneratedAnswer(
                    question_id=qid,
                    content=q["content"],
                    category=q["category"],
                    error="AI generation failed",
                )
            )
            continue

        # Persist to questions.answer_ai so frontend AnswerBlock can show it.
        try:
            async with session_scope() as wsession:
                await wsession.execute(
                    sa_text(
                        "UPDATE questions SET answer_ai = :ans, answer_ai_version = :ver WHERE id = :qid AND content=:content AND category IS NOT DISTINCT FROM :category"
                    ),
                    {
                        "ans": answer,
                        "ver": settings.answer_prompt_version,
                        "qid": qid,
                        "content": q["content"],
                        "category": q["category"],
                    },
                )
                await wsession.commit()
            from .cache import invalidate_read_caches

            await invalidate_read_caches()
        except Exception:  # noqa: BLE001  # ponytail: DB write is best-effort here; don't fail the whole bridge call
            log.error("bridge.write_answer_ai_failed", qid=qid, exc_info=True)

        # Naive importance heuristic: longer question = more likely to be complex.
        score = 3
        if len(q["content"]) > 80:
            score = 4
        if len(q["content"]) > 200:
            score = 5
        results.append(
            BridgeGeneratedAnswer(
                question_id=qid,
                content=q["content"],
                category=q["category"],
                generated_answer=answer,
                importance_score=score,
            )
        )

    from .cache import invalidate_read_caches

    await invalidate_read_caches()
    return BridgeGenerateResponse(answers=results)


@router.post("/export", response_model=BridgeExportResponse)
async def export_to_daily_prep(req: BridgeExportRequest) -> BridgeExportResponse:
    """Forward confirmed cards to daily-interview-prep bulk-import."""
    if not settings.daily_prep_token:
        raise HTTPException(502, "八股服务未配置 Token，请在 .env 中设置 DAILY_PREP_TOKEN")
    if not settings.daily_prep_api_url:
        raise HTTPException(502, "八股服务地址未配置")

    url = f"{settings.daily_prep_api_url.rstrip('/')}/cards/bulk-import"
    headers = {"Authorization": f"Bearer {settings.daily_prep_token}"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json={"cards": [c.model_dump() for c in req.cards]},
                headers=headers,
            )
    except httpx.ConnectError:
        raise HTTPException(502, "八股服务不可达")
    except httpx.TimeoutException:
        raise HTTPException(502, "八股服务超时")

    if resp.status_code == 401:
        raise HTTPException(502, "八股服务认证失败，请检查 Token 配置")
    if resp.status_code >= 400:
        log.error("bridge.export_failed", status=resp.status_code, body=resp.text)
        raise HTTPException(502, f"八股服务返回错误 {resp.status_code}")

    data = resp.json()
    return BridgeExportResponse(
        imported=data.get("imported", 0),
        skipped=data.get("skipped", 0),
        skipped_reasons=data.get("skipped_reasons", []),
    )
