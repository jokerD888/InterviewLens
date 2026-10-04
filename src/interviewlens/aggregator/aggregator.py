"""Aggregator: bucket questions by (company, position, period), dedup by
embedding similarity, then ask DeepSeek to summarise into markdown.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import openai
from pydantic import ValidationError
from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import settings
from ..db import (
    Company,
    Position,
    Post,
    Question,
    Summary,
    session_scope,
)
from ..embedding import EMBEDDING_VERSION, cosine_matrix, embed_texts
from ..errors import swallow
from ..llm.aggregator_schema import AggregatorResult
from ..llm.deepseek import get_client
from ..llm.prompts import (
    build_aggregator_messages,
    render_aggregator_md,
)
from ..logging import log
from ..observability import incr_tokens

DEFAULT_TOP_N: int | None = None  # full-bucket statistics by default
DEFAULT_PAGE_SIZE = 512
DEFAULT_LLM_MAX_CLUSTERS = 100
DUP_SIM_THRESHOLD = 0.92  # questions with cosine >= this collapse into one cluster
MIN_CONTENT_SCORE = 30
# Backward-compatible import/name for CLI callers; the threshold is now
# explicitly a stable content-completeness threshold.
MIN_QUALITY_SCORE = MIN_CONTENT_SCORE
MAX_OUTPUT_ATTEMPTS = 2  # initial generation + one corrective prompt
MAX_TRANSPORT_ATTEMPTS = 3
AGGREGATOR_FINGERPRINT_VERSION = 2


class AggregatorOutputError(RuntimeError):
    """The model response could not be parsed or failed business validation."""


@dataclass(slots=True)
class AggregateOutcome:
    company_id: int
    position_id: int
    period: str
    sample_count: int
    summary_chars: int
    cache_hit_questions: int
    written: bool
    skip_reason: str | None = None


def _period_for(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    quarter = (dt.month - 1) // 3 + 1
    return f"{dt.year}Q{quarter}"


async def _resolve_canonical_ids(
    *, company: str, position: str
) -> tuple[int | None, int | None]:
    async with session_scope() as session:
        c_id = (
            await session.execute(select(Company.id).where(Company.canonical == company))
        ).scalar_one_or_none()
        p_id = (
            await session.execute(select(Position.id).where(Position.canonical == position))
        ).scalar_one_or_none()
    return c_id, p_id


async def _fetch_candidate_questions(
    *,
    company_id: int,
    position_id: int,
    period: str | None,
    top_n: int | None,
    min_quality: int,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[dict]:
    """Read a bucket in stable pages, optionally applying an explicit cap.

    ``top_n=None`` means all eligible questions.  Pagination controls the
    database result size; it does not change the statistical population.
    """
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if top_n is not None and top_n <= 0:
        return []

    results: list[dict] = []
    after_score: int | None = None
    after_id: int | None = None
    while top_n is None or len(results) < top_n:
        remaining = None if top_n is None else top_n - len(results)
        limit = page_size if remaining is None else min(page_size, remaining)
        keyset_clause = ""
        if after_score is not None and after_id is not None:
            keyset_clause = """
              AND (
                  bp.content_score < :after_score
                  OR (bp.content_score = :after_score AND q.id < :after_id)
              )
            """
        sql = f"""
        WITH bucket_posts AS (
            SELECT po.id, po.posted_at,
                   COALESCE(po.content_score, 0) AS content_score
            FROM posts po
            JOIN post_company_position pcp ON pcp.post_id = po.id
            WHERE pcp.company_id = :c
              AND pcp.position_id = :p
              AND po.extract_status = 'done'
              AND COALESCE(po.content_score, 0) >= :min_q
              AND (
                  CAST(:period AS TEXT) IS NULL
                  OR to_char(po.posted_at, 'YYYY"Q"Q') = :period
              )
        )
        SELECT q.id, q.post_id, q.content, q.category, q.answer_brief,
               bp.content_score, p.source_url
        FROM questions q
        JOIN bucket_posts bp ON bp.id = q.post_id
        JOIN posts p ON p.id = bp.id
        WHERE q.embedding IS NOT NULL
          AND q.embedding_model = :embedding_model
          AND q.embedding_version = :embedding_version
        {keyset_clause}
        ORDER BY bp.content_score DESC, q.id DESC
        LIMIT :page_size
        """
        params = {
            "c": company_id,
            "p": position_id,
            "period": period,
            "min_q": min_quality,
            "page_size": limit,
            "embedding_model": settings.embedding_model,
            "embedding_version": EMBEDDING_VERSION,
        }
        if after_score is not None and after_id is not None:
            params.update({"after_score": after_score, "after_id": after_id})
        async with session_scope() as session:
            rows = (await session.execute(sa_text(sql), params)).all()
        if not rows:
            break
        results.extend(
            {
                "id": r[0],
                "content": r[1],
                "category": r[2],
                "answer_brief": r[3],
                "content_score": r[4],
                # Compatibility for prompt/tests written before the split.
                "quality_score": r[4],
                "source_url": r[5],
            }
            for r in rows
        )
        after_score = int(rows[-1][4] or 0)
        after_id = int(rows[-1][0])
        if len(rows) < limit:
            break
    return results


async def _fetch_embeddings(
    question_ids: list[int],
    *,
    batch_size: int = DEFAULT_PAGE_SIZE,
) -> dict[int, np.ndarray]:
    if not question_ids:
        return {}
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    sql = "SELECT id, embedding::text FROM questions WHERE id = ANY(:ids)"
    out: dict[int, np.ndarray] = {}
    for start in range(0, len(question_ids), batch_size):
        chunk = question_ids[start : start + batch_size]
        async with session_scope() as session:
            rows = (await session.execute(sa_text(sql), {"ids": chunk})).all()
        for qid, vec_str in rows:
            if vec_str is None:
                continue
            # pgvector text format: "[0.1,0.2,...]"
            cleaned = vec_str.strip().strip("[]")
            if not cleaned:
                continue
            out[qid] = np.fromstring(cleaned, sep=",", dtype=np.float32)
    return out


def _cluster_questions(
    questions: list[dict],
    embeddings: dict[int, np.ndarray],
    *,
    threshold: float,
    block_size: int = 512,
) -> list[dict]:
    """Cluster a complete bucket with blockwise NumPy graph construction.

    Similarity edges are added for every pair at or above ``threshold`` and
    Union-Find computes connected components.  This is order-independent and
    gives each component's true frequency within the supplied population.
    ``block_size`` bounds the temporary similarity matrix, while the overall
    exact comparison remains O(n²d).
    """
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    n = len(questions)
    if n == 0:
        return []

    parent = list(range(n))
    sizes = [1] * n

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left == root_right:
            return
        if sizes[root_left] < sizes[root_right]:
            root_left, root_right = root_right, root_left
        parent[root_right] = root_left
        sizes[root_left] += sizes[root_right]

    valid_indices: list[int] = []
    valid_vectors: list[np.ndarray] = []
    for index, question in enumerate(questions):
        vector = embeddings.get(question["id"])
        if vector is None or vector.size == 0:
            continue
        if vector.ndim != 1:
            raise ValueError(f"embedding for question {question['id']} is not 1-D")
        if not np.isfinite(vector).all() or float(np.linalg.norm(vector)) <= 1e-12:
            continue
        valid_indices.append(index)
        valid_vectors.append(np.asarray(vector, dtype=np.float32))

    if valid_vectors:
        matrix = np.stack(valid_vectors)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / norms
        for start in range(0, len(valid_indices), block_size):
            stop = min(start + block_size, len(valid_indices))
            left = matrix[start:stop]
            for other_start in range(start, len(valid_indices), block_size):
                other_stop = min(other_start + block_size, len(valid_indices))
                right = matrix[other_start:other_stop]
                similarities = cosine_matrix(left, right)
                pairs = np.argwhere(similarities >= threshold)
                for left_offset, right_offset in pairs:
                    left_pos = start + int(left_offset)
                    right_pos = other_start + int(right_offset)
                    if left_pos >= right_pos:
                        continue
                    union(valid_indices[left_pos], valid_indices[right_pos])

    components: dict[int, list[int]] = {}
    for index in range(n):
        components.setdefault(find(index), []).append(index)

    clusters: list[dict] = []
    for members in components.values():
        representative = min(
            members,
            key=lambda index: (
                -(questions[index].get("content_score", questions[index].get("quality_score")) or 0),
                questions[index]["id"],
            ),
        )
        post_ids = {
            questions[index].get("post_id")
            for index in members
            if questions[index].get("post_id") is not None
        }
        sorted_members = sorted(members, key=lambda idx: questions[idx]["id"])
        cluster = {
            **questions[representative],
            "freq": len(members),
            "question_count": len(members),
            "post_count": len(post_ids) if post_ids else 1,
            "member_ids": [questions[idx]["id"] for idx in sorted_members],
            "member_contents": [questions[idx]["content"] for idx in sorted_members],
            "member_post_ids": sorted(post_ids),
        }
        clusters.append(cluster)

    clusters.sort(
        key=lambda x: (
            -x.get("question_count", x.get("freq", 1)),
            -x.get("post_count", 1),
            -(x.get("content_score", x.get("quality_score")) or 0),
            x.get("id", 0),
        )
    )
    return clusters


def _normalise_question_text(value: str) -> str:
    """Normalise only whitespace for source-question membership checks."""
    return " ".join(value.split())


def _build_input_fingerprint(
    *,
    questions: list[dict],
    period: str | None,
    top_n: int | None,
    min_quality: int,
    dedup_threshold: float,
    llm_max_clusters: int = DEFAULT_LLM_MAX_CLUSTERS,
) -> str:
    """Build a stable cache key for every input that affects a summary.

    The list order is intentional: SQL selection order determines an explicit
    ``top_n`` boundary.  With the default ``top_n=None`` the complete bucket
    is part of the fingerprint.  The version must be bumped when the
    aggregation algorithm, prompt, or embedding contract changes.
    """
    payload = {
        "fingerprint_version": AGGREGATOR_FINGERPRINT_VERSION,
        "period": period,
        "top_n": top_n,
        "min_quality": min_quality,
        "dedup_threshold": dedup_threshold,
        "llm_max_clusters": llm_max_clusters,
        "chat_model": settings.deepseek_model_chat,
        "embedding_model": settings.embedding_model,
        "embedding_version": EMBEDDING_VERSION,
        "questions": [
            {
                "id": q.get("id"),
                "content": q.get("content"),
                "category": q.get("category"),
                "content_score": q.get("content_score"),
            }
            for q in questions
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_aggregator_output(
    raw_content: str,
    *,
    questions: list[dict],
) -> AggregatorResult:
    """Parse, validate, and fact-check one Aggregator response.

    ``json-repair`` is intentionally only a syntax-recovery step.  The
    Pydantic model remains the runtime contract, and question references are
    checked against the exact input bucket (apart from whitespace).
    """
    if not raw_content.strip():
        raise AggregatorOutputError("Aggregator returned empty content")

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as first_error:
        try:
            from json_repair import repair_json

            data = json.loads(repair_json(raw_content))
        except Exception as repair_error:  # noqa: BLE001 - parser boundary
            raise AggregatorOutputError(
                f"Invalid JSON after repair: {repair_error}"
            ) from first_error

    if not isinstance(data, dict):
        raise AggregatorOutputError("Aggregator JSON top level must be an object")

    try:
        result = AggregatorResult.model_validate(data)
    except ValidationError as exc:
        raise AggregatorOutputError(
            f"Aggregator schema validation failed: {str(exc)[:1200]}"
        ) from exc

    known_questions = {
        _normalise_question_text(str(q.get("content", ""))) for q in questions
    }
    cluster_by_content: dict[str, dict] = {}
    for cluster in questions:
        norm_rep = _normalise_question_text(str(cluster.get("content", "")))
        if norm_rep:
            known_questions.add(norm_rep)
            cluster_by_content[norm_rep] = cluster
        for member_text in cluster.get("member_contents", []):
            norm_mem = _normalise_question_text(str(member_text))
            if norm_mem:
                known_questions.add(norm_mem)
                cluster_by_content[norm_mem] = cluster

    referenced_questions = [
        *(
            question
            for topic in result.high_frequency_topics
            for question in topic.sample_questions
        ),
        *(
            question
            for edge in result.edge_cases
            for question in edge.questions
        ),
    ]
    unknown_questions = [
        question
        for question in referenced_questions
        if _normalise_question_text(question) not in known_questions
    ]
    if unknown_questions:
        preview = "; ".join(unknown_questions[:2])[:500]
        raise AggregatorOutputError(
            f"Aggregator referenced question(s) not present in input: {preview}"
        )

    # Backend frequency and post-count calculation from deduplicated clusters
    for topic in result.high_frequency_topics:
        seen_cluster_keys: set[int | str] = set()
        matched_clusters: list[dict] = []
        for q_text in topic.sample_questions:
            norm_q = _normalise_question_text(str(q_text))
            matched = cluster_by_content.get(norm_q)
            if matched is not None:
                ckey = matched.get("id", norm_q)
                if ckey not in seen_cluster_keys:
                    seen_cluster_keys.add(ckey)
                    matched_clusters.append(matched)

        if matched_clusters:
            calc_q_count = 0
            for c in matched_clusters:
                if "question_count" in c:
                    calc_q_count += int(c["question_count"])
                elif "freq" in c:
                    calc_q_count += int(c["freq"])
            if calc_q_count == 0:
                calc_q_count = topic.frequency or len(matched_clusters)

            all_posts: set[int] = set()
            for c in matched_clusters:
                if c.get("member_post_ids"):
                    all_posts.update(c["member_post_ids"])
                elif c.get("post_id"):
                    all_posts.add(c["post_id"])
            if all_posts:
                calc_post_count = max(1, len(all_posts))
            else:
                calc_post_count = max(1, sum(int(c.get("post_count", 1)) for c in matched_clusters))
        else:
            calc_q_count = topic.frequency or len(topic.sample_questions)
            calc_post_count = 1

        topic.frequency = calc_q_count
        topic.question_count = calc_q_count
        topic.post_count = calc_post_count

    result.high_frequency_topics.sort(
        key=lambda t: (-t.frequency, -(t.post_count or 1), t.topic)
    )

    return result


def _merge_usage(total: dict | None, current: dict | None) -> dict | None:
    """Add token counters across corrective attempts."""
    if current is None:
        return total
    merged = dict(total or {})
    for key, value in current.items():
        if isinstance(value, (int, float)):
            merged[key] = (merged.get(key) or 0) + value
        elif key not in merged:
            merged[key] = value
    return merged


async def _create_aggregator_response(*, client, messages: list[dict], temperature: float):
    """Call the provider with transport-only retries.

    Output validation is handled by ``_summarise`` because invalid output
    needs a corrective prompt, not a blind transport retry.
    """
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(MAX_TRANSPORT_ATTEMPTS),
        wait=wait_exponential(min=1, max=8),
        retry=retry_if_exception_type((openai.APIError, asyncio.TimeoutError)),
        reraise=True,
    ):
        with attempt:
            return await client.chat.completions.create(
                model=settings.deepseek_model_chat,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=8192,
                response_format={"type": "json_object"},  # type: ignore[arg-type]
            )
    raise RuntimeError("unreachable")


async def _summarise(
    *,
    company: str,
    position: str,
    period: str,
    questions: list[dict],
    sample_count: int | None = None,
    trace=None,
) -> tuple[str, dict | None]:
    """Generate validated structured JSON via DeepSeek, then render Markdown.

    A second attempt is made only for an empty, malformed, or semantically
    invalid model response.  The retry keeps JSON mode and adds a corrective
    prompt; raw model output is never persisted.
    """
    base_messages = build_aggregator_messages(
        company=company,
        position=position,
        period=period,
        questions=questions,
        sample_count=len(questions) if sample_count is None else sample_count,
    )
    client = get_client()
    usage_total: dict | None = None

    messages = base_messages
    result: AggregatorResult | None = None
    last_error: AggregatorOutputError | None = None
    for attempt_no in range(1, MAX_OUTPUT_ATTEMPTS + 1):
        resp = await _create_aggregator_response(
            client=client,
            messages=messages,
            temperature=0.3 if attempt_no == 1 else 0.0,
        )
        current_usage = resp.usage.model_dump() if resp.usage else None
        usage_total = _merge_usage(usage_total, current_usage)
        if current_usage:
            await incr_tokens(
                prompt=int(current_usage.get("prompt_tokens") or 0),
                completion=int(current_usage.get("completion_tokens") or 0),
            )
        raw_content = resp.choices[0].message.content or ""

        try:
            result = _parse_aggregator_output(raw_content, questions=questions)
            break
        except AggregatorOutputError as exc:
            last_error = exc
            if attempt_no == MAX_OUTPUT_ATTEMPTS:
                raise
            log.warning(
                "aggregate.output_retry",
                attempt=attempt_no,
                error=str(exc),
                company=company,
                position=position,
                period=period,
            )
            messages = [
                *base_messages,
                {
                    "role": "user",
                    "content": (
                        "上一次输出未通过校验："
                        f"{str(exc)[:1000]}\n"
                        "请重新生成，只返回符合要求的 JSON；不要解释，不要返回 Markdown，"
                        "题目引用必须逐字来自输入列表。"
                    ),
                },
            ]

    if result is None:
        raise last_error or AggregatorOutputError("Aggregator returned no result")

    content_md = render_aggregator_md(result.model_dump())

    if trace is not None:
        with swallow("aggregate.trace_record_failed"):  # Layer A
            trace.generation(
                name="aggregator.summary",
                model=settings.deepseek_model_chat,
                input=messages,
                output=content_md,
                usage=usage_total,
            ).end()
    return content_md, usage_total


async def aggregate_one(
    *,
    company: str,
    position: str,
    period: str | None = None,
    top_n: int | None = DEFAULT_TOP_N,
    min_quality: int = MIN_QUALITY_SCORE,
    dedup_threshold: float = DUP_SIM_THRESHOLD,
    llm_max_clusters: int = DEFAULT_LLM_MAX_CLUSTERS,
    write: bool = True,
    trace=None,
) -> AggregateOutcome:
    """Run aggregation for one (company, position, period) bucket."""
    c_id, p_id = await _resolve_canonical_ids(company=company, position=position)
    if c_id is None or p_id is None:
        return AggregateOutcome(
            company_id=c_id or 0,
            position_id=p_id or 0,
            period=period or "",
            sample_count=0,
            summary_chars=0,
            cache_hit_questions=0,
            written=False,
            skip_reason="unknown_canonical",
        )

    period_label = period or "all"
    if llm_max_clusters <= 0:
        raise ValueError("llm_max_clusters must be positive")
    log.info(
        "aggregate.start",
        company=company,
        position=position,
        period=period_label,
        top_n=top_n,
    )

    raw = await _fetch_candidate_questions(
        company_id=c_id,
        position_id=p_id,
        period=period if period and period != "all" else None,
        top_n=top_n,
        min_quality=min_quality,
    )
    if not raw:
        return AggregateOutcome(
            company_id=c_id,
            position_id=p_id,
            period=period_label,
            sample_count=0,
            summary_chars=0,
            cache_hit_questions=0,
            written=False,
            skip_reason="no_questions",
        )

    input_fingerprint = _build_input_fingerprint(
        questions=raw,
        period=period_label,
        top_n=top_n,
        min_quality=min_quality,
        dedup_threshold=dedup_threshold,
        llm_max_clusters=llm_max_clusters,
    )

    # Skip only when the complete aggregation input and algorithm contract
    # match.  Counts alone cannot detect replacement questions or parameter
    # changes, and sample_count is a presentation field rather than a cache key.
    if write:
        async with session_scope() as session:
            existing = (
                await session.execute(
                    select(Summary).where(
                        Summary.company_id == c_id,
                        Summary.position_id == p_id,
                        Summary.period == period_label,
                    )
                )
            ).scalar_one_or_none()
        if existing is not None and existing.input_fingerprint == input_fingerprint:
            log.info(
                "aggregate.cached",
                company=company,
                position=position,
                period=period_label,
                samples=len(raw),
            )
            return AggregateOutcome(
                company_id=c_id,
                position_id=p_id,
                period=period_label,
                sample_count=len(raw),
                summary_chars=0,
                cache_hit_questions=0,
                written=False,
                skip_reason="cached",
            )

    embeddings = await _fetch_embeddings([q["id"] for q in raw])
    clusters = _cluster_questions(raw, embeddings, threshold=dedup_threshold)
    llm_questions = clusters[:llm_max_clusters]
    log.info(
        "aggregate.clustered",
        raw=len(raw),
        clusters=len(clusters),
        llm_clusters=len(llm_questions),
    )

    summary_md, _usage = await _summarise(
        company=company,
        position=position,
        period=period_label,
        questions=llm_questions,
        sample_count=len(raw),
        trace=trace,
    )

    if write:
        async with session_scope() as session:
            existing = (
                await session.execute(
                    select(Summary).where(
                        Summary.company_id == c_id,
                        Summary.position_id == p_id,
                        Summary.period == period_label,
                    )
                )
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if existing is None:
                session.add(
                    Summary(
                        company_id=c_id,
                        position_id=p_id,
                        period=period_label,
                        content_md=summary_md,
                        sample_count=len(raw),
                        input_fingerprint=input_fingerprint,
                        updated_at=now,
                    )
                )
            else:
                existing.content_md = summary_md
                existing.sample_count = len(raw)
                existing.input_fingerprint = input_fingerprint
                existing.updated_at = now

    return AggregateOutcome(
        company_id=c_id,
        position_id=p_id,
        period=period_label,
        sample_count=len(raw),
        summary_chars=len(summary_md),
        cache_hit_questions=0,
        written=write,
    )


async def aggregate_all(
    *,
    top_n: int | None = DEFAULT_TOP_N,
    min_quality: int = MIN_QUALITY_SCORE,
    period: str | None = None,
    llm_max_clusters: int = DEFAULT_LLM_MAX_CLUSTERS,
    write: bool = True,
) -> list[AggregateOutcome]:
    """Find every (company, position) pair with data and run aggregate_one."""
    sql = """
    SELECT DISTINCT c.canonical, p.canonical
    FROM post_company_position pcp
    JOIN companies c ON c.id = pcp.company_id
    JOIN positions p ON p.id = pcp.position_id
    JOIN posts po ON po.id = pcp.post_id
    WHERE po.extract_status = 'done' AND COALESCE(po.content_score, 0) >= :min_q
    """
    async with session_scope() as session:
        pairs = (await session.execute(sa_text(sql), {"min_q": min_quality})).all()

    log.info("aggregate.all_pairs", n=len(pairs))
    results: list[AggregateOutcome] = []
    sem = asyncio.Semaphore(20)  # DeepSeek flash supports 2500 CCU

    async def _one(c_name: str, p_name: str) -> AggregateOutcome | None:
        async with sem:
            try:
                return await aggregate_one(
                    company=c_name,
                    position=p_name,
                    period=period,
                    top_n=top_n,
                    min_quality=min_quality,
                    llm_max_clusters=llm_max_clusters,
                    write=write,
                )
            except (openai.APIError, SQLAlchemyError, asyncio.TimeoutError, RuntimeError):
                # Layer C: one bucket failing externally must not abort the batch,
                # but logic bugs (TypeError/AttributeError) bubble up.
                log.error("aggregate.pair_failed", company=c_name, position=p_name, exc_info=True)
                return None

    gathered = await asyncio.gather(*(_one(c, p) for c, p in pairs))
    results = [r for r in gathered if r is not None]
    return results
