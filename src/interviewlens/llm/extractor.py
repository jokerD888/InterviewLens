"""High-level Extractor: cleaned_text → ExtractedPost (cached)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..config import settings
from ..crawler.cleaner import strip_nowcoder_noise
from ..logging import log
from ..observability import incr_cache
from ..position_taxonomy import (
    DOMAINS,
    SKILL_ALIASES,
    SKILLS,
    SPECIALIZATIONS,
    PositionCategory,
    PositionProfile,
    validate_evidence,
)
from .cache import cache_get, cache_set, make_cache_key
from .deepseek import ToolCallResult, call_tool
from .prompts import build_extractor_messages, get_extractor_prompt_version
from .schema import EXTRACT_FUNCTION_SCHEMA, ExtractedPost


def _parse_extraction(arguments: dict, author_text: str) -> ExtractedPost:
    """Drop only out-of-vocabulary optional facets at the model boundary.

    Admin writes still use strict PositionProfile validation. A provider's
    invented skill must not discard correctly extracted interview questions.
    Malformed structures and invalid primary categories still fail validation.
    """
    arguments = deepcopy(arguments)
    rounds = arguments.get("rounds")
    for round_item in rounds if isinstance(rounds, list) else []:
        if not isinstance(round_item, dict) or not isinstance(round_item.get("questions"), list):
            continue
        questions = round_item["questions"]
        kept = [
            q
            for q in questions
            if not (
                isinstance(q, dict)
                and isinstance(q.get("content"), str)
                and len(q["content"].strip()) < 2
            )
        ]
        if len(kept) != len(questions):
            log.warning("extractor.dropped_question_fragments", count=len(questions) - len(kept))
        round_item["questions"] = kept
    profiles = arguments.get("position_profiles")
    for profile in profiles if isinstance(profiles, list) else []:
        if not isinstance(profile, dict):
            continue
        # Uncertain/out-of-scope output never becomes a classified role just
        # because the model also supplied a category. Prefer the conservative
        # state rather than guessing which contradictory field was intended.
        if profile.get("status", "uncertain") in ("uncertain", "out_of_scope"):
            if profile.get("category") in set(PositionCategory):
                profile["category"] = None
        elif profile.get("status") == "classified" and profile.get("category") is None:
            profile["status"] = "uncertain"
        for field, vocabulary in (
            ("specializations", SPECIALIZATIONS),
            ("domains", DOMAINS),
            ("skills", SKILLS),
        ):
            values = profile.get(field, [])
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                continue
            normalized = [SKILL_ALIASES.get(v, v) if field == "skills" else v for v in values]
            rejected = sorted(set(normalized) - set(vocabulary))
            if rejected:
                log.warning("extractor.dropped_unsupported_facets", field=field, values=rejected)
            profile[field] = [v for v in normalized if v in vocabulary]
        evidence = profile.get("evidence", [])
        if isinstance(evidence, list):
            vocabularies = {
                "specializations": SPECIALIZATIONS,
                "domains": DOMAINS,
                "skills": SKILLS,
            }
            profile["evidence"] = [
                e
                for e in evidence
                if not isinstance(e, dict)
                or e.get("field") not in vocabularies
                or not isinstance(e.get("value"), str)
                or (
                    SKILL_ALIASES.get(e.get("value"), e.get("value"))
                    if e.get("field") == "skills"
                    else e.get("value")
                )
                in vocabularies[e["field"]]
            ]
    parsed = ExtractedPost.model_validate(arguments)
    parsed.position_profiles = [validate_evidence(p, author_text) for p in parsed.position_profiles]
    if not parsed.position_profiles:
        parsed.position_profiles = [PositionProfile()]
    return parsed


async def extract_from_text(
    cleaned_text: str,
    *,
    post_id: int | None = None,
    use_cache: bool = True,
    trace: Any | None = None,
) -> tuple[ExtractedPost, dict[str, Any]]:
    """Run Extractor on already-cleaned text.

    When ``trace`` is provided (a Langfuse trace), the LLM call is recorded
    as a generation underneath it. Otherwise an ad-hoc trace is created
    inside ``call_tool``.

    Returns ``(parsed, info)`` where ``info`` carries usage / cache_hit / model.
    """
    if not cleaned_text or not cleaned_text.strip():
        raise ValueError("cleaned_text is empty")

    cleaned_text = strip_nowcoder_noise(cleaned_text)
    if not cleaned_text.strip():
        raise ValueError("author content is empty after cleaning")
    version = get_extractor_prompt_version()
    cache_key = make_cache_key(
        namespace="extract",
        payload={
            "text": cleaned_text,
            "model": settings.deepseek_model_chat,
            "schema": EXTRACT_FUNCTION_SCHEMA,
        },
        version=version,
    )

    if use_cache:
        cached = await cache_get(cache_key)
        if cached is not None:
            log.info("extract.cache_hit", post_id=post_id, key=cache_key[-12:])
            await incr_cache(hit=True)
            parsed = _parse_extraction(cached["arguments"], cleaned_text)
            return parsed, {
                "cache_hit": True,
                "usage": None,
                "model": cached.get("model"),
                "version": version,
            }
        await incr_cache(hit=False)

    messages = build_extractor_messages(cleaned_text)
    result: ToolCallResult = await call_tool(
        messages=messages,
        tools=[EXTRACT_FUNCTION_SCHEMA],
        tool_choice={
            "type": "function",
            "function": {"name": "extract_interview_post"},
        },
        max_tokens=8192,
        trace_name="extractor",
        trace_metadata={"post_id": post_id, "prompt_version": version},
        trace=trace,
    )

    # Normalise level field: LLM may return variants like "暑期实习" → "实习"
    args = result.arguments
    raw_level = args.get("level", "")
    if raw_level and "实习" in str(raw_level):
        args["level"] = "实习"
    elif raw_level and "校招" in str(raw_level):
        args["level"] = "校招"
    elif raw_level and "社招" in str(raw_level):
        args["level"] = "社招"

    # Normalise round_type and category: fallback to "其他" when LLM invents values
    valid_round_types = {
        "技术一面",
        "技术二面",
        "技术三面",
        "技术四面",
        "技术五面",
        "HR面",
        "交叉面",
        "笔试",
        "主管面",
        "其他",
    }
    valid_categories = {
        "算法",
        "数据结构",
        "系统设计",
        "数据库",
        "操作系统",
        "网络",
        "语言基础",
        "项目",
        "深度学习",
        "计算机体系结构",
        "AI基础",
        "大模型",
        "HR",
        "其他",
    }
    for rd in args.get("rounds") or []:
        if rd.get("round_type") and rd["round_type"] not in valid_round_types:
            log.info("extractor.normalized_round_type", value=rd["round_type"])
            rd["round_type"] = "其他"
        for q in rd.get("questions") or []:
            if q.get("category") and q["category"] not in valid_categories:
                log.info("extractor.normalized_category", value=q["category"])
                q["category"] = "其他"

    parsed = _parse_extraction(args, cleaned_text)

    if use_cache:
        await cache_set(
            cache_key,
            {
                "arguments": parsed.model_dump(mode="json"),
                "model": result.model,
                "usage": result.usage,
            },
        )

    return parsed, {
        "cache_hit": False,
        "usage": result.usage,
        "model": result.model,
        "version": version,
    }
