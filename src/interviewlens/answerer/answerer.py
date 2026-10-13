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

from ..db.processing_reads import READY_POST_SQL
from ..config import settings
from ..db import session_scope
from ..errors import swallow
from ..llm.cache import cache_get, cache_set, make_cache_key
from ..llm.deepseek import get_client
from ..llm.prompts import build_answerer_messages
from ..logging import log
from ..observability import get_langfuse

ANSWER_NAMESPACE = "answer"
CONCURRENCY = settings.llm_concurrency
MAX_TOKENS = 1500


@dataclass(slots=True)
class AnswerOutcome:
    generated: int = 0
    cache_hits: int = 0
    skipped: int = 0
    failed: int = 0


async def generate_one(*, content: str, category: str | None, trace=None, use_cache: bool = True) -> str | None:
    """Generate (or fetch cached) AI answer for one question. None on failure."""
    key = make_cache_key(
        namespace=ANSWER_NAMESPACE,
        payload={"content": content, "category": category, "model": settings.deepseek_model_chat},
        version=settings.answer_prompt_version,
    )
    cached = await cache_get(key) if use_cache else None
    if cached and cached.get("answer"):
        return cached["answer"]

    messages = build_answerer_messages(content=content, category=category)
    own_client = None
    generation = None
    with swallow("answer.trace_create_failed"):
        if trace is None:
            own_client = get_langfuse()
            if own_client is not None:
                trace = own_client.trace(
                    name="answerer",
                    input={"content": content, "category": category},
                    metadata={
                        "prompt_version": settings.answer_prompt_version,
                    },
                )
        if trace is not None:
            generation = trace.generation(
                name="answerer.answer",
                model=settings.deepseek_model_chat,
                input=messages,
            )
    try:
        try:
            client = get_client()
            resp = await client.chat.completions.create(
                model=settings.deepseek_model_chat,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.3,
                max_tokens=MAX_TOKENS,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except (openai.APIError, TimeoutError) as exc:
            # Layer C: external LLM failure degrades to None; logic bugs bubble.
            log.error("answer.llm_failed", exc_info=True)
            if generation is not None:
                with swallow("answer.trace_record_failed"):
                    generation.end(level="ERROR", status_message=type(exc).__name__)
            return None

        answer = (resp.choices[0].message.content or "").strip()
        truncated = getattr(resp.choices[0], "finish_reason", None) == "length"
        if truncated:
            log.warning("answer.truncated", max_tokens=MAX_TOKENS)
            answer = ""
        usage = resp.usage.model_dump() if resp.usage else None
        if generation is not None:
            with swallow("answer.trace_record_failed"):  # Layer A
                if answer:
                    generation.end(output=answer, usage=usage)
                else:
                    generation.end(
                        output=answer,
                        usage=usage,
                        level="ERROR",
                        status_message="Truncated answer" if truncated else "Empty answer",
                    )
        if own_client is not None and trace is not None:
            with swallow("answer.trace_record_failed"):
                trace.update(output=answer)

        if answer:
            await cache_set(key, {"answer": answer})
        return answer or None
    except BaseException as exc:
        if generation is not None:
            with swallow("answer.trace_record_failed"):
                generation.end(level="ERROR", status_message=type(exc).__name__)
        raise
    finally:
        if own_client is not None:
            with swallow("answer.trace_flush_failed"):
                from ..tracing import end_trace
                end_trace(trace)
                await asyncio.to_thread(own_client.flush)


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
        "po.extract_status = 'done'", READY_POST_SQL,
        "COALESCE(po.content_score, 0) >= :min_q",
    ]
    params: dict[str, object] = {"min_q": min_quality, "ver": settings.answer_prompt_version}
    if not regenerate:
        clauses.append("(q.answer_ai IS NULL OR q.answer_ai_version < :ver)")
    joins = "JOIN posts po ON po.id = q.post_id"
    if company or position:
        from ..db.attribution import question_scope_sql

        clauses.append(
            question_scope_sql(
                company=":company" if company else None, position=":position" if position else None
            )
        )
        params.update({"company": company, "position": position})
    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT :limit"
        params["limit"] = limit

    sql = f"""
    SELECT DISTINCT q.id, q.content, q.category
    FROM questions q
    {joins}
    WHERE {" AND ".join(clauses)}
    ORDER BY q.id
    {limit_sql}
    """
    async with session_scope() as session:
        rows = (await session.execute(sa_text(sql), params)).all()
    return [{"id": r[0], "content": r[1], "category": r[2]} for r in rows]


async def _write_answer(qid: int, answer: str) -> None:
    async with session_scope() as session:
        await session.execute(
            sa_text("UPDATE questions SET answer_ai = :a, answer_ai_version = :v WHERE id = :id"),
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
            answer = await generate_one(content=t["content"], category=t["category"], use_cache=not regenerate)
            if answer is None:
                outcome.failed += 1
            else:
                await _write_answer(t["id"], answer)
                outcome.generated += 1
            done += 1
            if done % 100 == 0 or done == total:
                log.info(
                    "answer.progress",
                    done=done,
                    total=total,
                    generated=outcome.generated,
                    failed=outcome.failed,
                )

    await asyncio.gather(*(_one(t) for t in targets))
    from ..api.cache import invalidate_read_caches

    await invalidate_read_caches()
    return outcome
