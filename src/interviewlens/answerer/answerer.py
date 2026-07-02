"""Answerer: per-question AI answer generation (offline).

For each eligible question, call DeepSeek once (never batched) so each answer
gets full attention. Length adapts to difficulty via the prompt. Results are
cached in Redis by question text + prompt version, then written to
questions.answer_ai.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import openai
from sqlalchemy import text as sa_text

from ..config import settings
from ..db import session_scope
from ..errors import swallow
from ..llm.cache import cache_get, cache_set, make_cache_key
from ..llm.deepseek import get_client
from ..llm.prompts import build_answerer_messages
from ..logging import log
from ..observability import incr_tokens

ANSWER_NAMESPACE = "answer"
CONCURRENCY = 100
MAX_TOKENS = 1500


@dataclass(slots=True)
class AnswerOutcome:
    generated: int = 0
    cache_hits: int = 0
    skipped: int = 0
    failed: int = 0


async def generate_one(
    *, content: str, category: str | None, trace=None
) -> str | None:
    """Generate (or fetch cached) AI answer for one question. None on failure."""
    key = make_cache_key(
        namespace=ANSWER_NAMESPACE,
        payload={"content": content},
        version=settings.answer_prompt_version,
    )
    cached = await cache_get(key)
    if cached and cached.get("answer"):
        return cached["answer"]

    messages = build_answerer_messages(content=content, category=category)
    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=settings.deepseek_model_chat,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.3,
            max_tokens=MAX_TOKENS,
        )
    except (openai.APIError, asyncio.TimeoutError) as exc:
        # Layer C: external LLM failure degrades to None; logic bugs bubble.
        log.error("answer.llm_failed", exc_info=True)
        return None

    answer = (resp.choices[0].message.content or "").strip()
    usage = resp.usage.model_dump() if resp.usage else None
    if usage:
        await incr_tokens(
            prompt=int(usage.get("prompt_tokens") or 0),
            completion=int(usage.get("completion_tokens") or 0),
        )
    if trace is not None:
        with swallow("answer.trace_record_failed"):  # Layer A
            trace.generation(
                name="answerer.answer",
                model=settings.deepseek_model_chat,
                input=messages,
                output=answer,
                usage=usage,
            ).end()

    if answer:
        await cache_set(key, {"answer": answer})
    return answer or None


async def _fetch_targets(
    *,
    company: str | None,
    position: str | None,
    limit: int | None,
    min_quality: int,
    regenerate: bool,
) -> list[dict]:
    """Select questions needing an AI answer."""
    clauses = [
        "po.extract_status = 'done'",
        "COALESCE(po.quality_score, 0) >= :min_q",
    ]
    params: dict[str, object] = {"min_q": min_quality, "ver": settings.answer_prompt_version}
    if not regenerate:
        clauses.append("(q.answer_ai IS NULL OR q.answer_ai_version < :ver)")
    joins = "JOIN posts po ON po.id = q.post_id"
    if company:
        joins += (
            " JOIN post_company_position pcp_c ON pcp_c.post_id = po.id"
            " JOIN companies c ON c.id = pcp_c.company_id"
        )
        clauses.append("c.canonical = :company")
        params["company"] = company
    if position:
        joins += (
            " JOIN post_company_position pcp_p ON pcp_p.post_id = po.id"
            " JOIN positions p ON p.id = pcp_p.position_id"
        )
        clauses.append("p.canonical = :position")
        params["position"] = position

    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT :limit"
        params["limit"] = limit

    sql = f"""
    SELECT DISTINCT q.id, q.content, q.category
    FROM questions q
    {joins}
    WHERE {' AND '.join(clauses)}
    ORDER BY q.id
    {limit_sql}
    """
    async with session_scope() as session:
        rows = (await session.execute(sa_text(sql), params)).all()
    return [{"id": r[0], "content": r[1], "category": r[2]} for r in rows]


async def _write_answer(qid: int, answer: str) -> None:
    async with session_scope() as session:
        await session.execute(
            sa_text(
                "UPDATE questions SET answer_ai = :a, answer_ai_version = :v WHERE id = :id"
            ),
            {"a": answer, "v": settings.answer_prompt_version, "id": qid},
        )


async def run_answers(
    *,
    company: str | None = None,
    position: str | None = None,
    limit: int | None = None,
    min_quality: int = 30,
    regenerate: bool = False,
) -> AnswerOutcome:
    """Generate AI answers for all eligible questions."""
    targets = await _fetch_targets(
        company=company,
        position=position,
        limit=limit,
        min_quality=min_quality,
        regenerate=regenerate,
    )
    log.info("answer.start", targets=len(targets))
    outcome = AnswerOutcome()
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    total = len(targets)

    async def _one(t: dict) -> None:
        nonlocal done
        async with sem:
            answer = await generate_one(content=t["content"], category=t["category"])
            if answer is None:
                outcome.failed += 1
            else:
                await _write_answer(t["id"], answer)
                outcome.generated += 1
            done += 1
            if done % 100 == 0 or done == total:
                log.info("answer.progress", done=done, total=total, generated=outcome.generated, failed=outcome.failed)

    await asyncio.gather(*(_one(t) for t in targets))
    return outcome
