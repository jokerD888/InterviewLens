"""High-level Extractor: cleaned_text → ExtractedPost (cached)."""
from __future__ import annotations

from typing import Any

from ..logging import log
from ..observability import incr_cache, incr_tokens
from .cache import cache_get, cache_set, make_cache_key
from .deepseek import ToolCallResult, call_tool
from .prompts import build_extractor_messages, get_extractor_prompt_version
from .schema import EXTRACT_FUNCTION_SCHEMA, ExtractedPost


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

    version = get_extractor_prompt_version()
    cache_key = make_cache_key(
        namespace="extract",
        payload={"text": cleaned_text},
        version=version,
    )

    if use_cache:
        cached = await cache_get(cache_key)
        if cached is not None:
            log.info("extract.cache_hit", post_id=post_id, key=cache_key[-12:])
            await incr_cache(hit=True)
            parsed = ExtractedPost.model_validate(cached["arguments"])
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

    parsed = ExtractedPost.model_validate(args)

    if result.usage:
        await incr_tokens(
            prompt=int(result.usage.get("prompt_tokens") or 0),
            completion=int(result.usage.get("completion_tokens") or 0),
        )

    if use_cache:
        await cache_set(
            cache_key,
            {
                "arguments": result.arguments,
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
