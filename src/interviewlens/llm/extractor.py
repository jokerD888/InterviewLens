"""High-level Extractor: cleaned_text → ExtractedPost (cached)."""
from __future__ import annotations

from typing import Any

from .cache import cache_get, cache_set, make_cache_key
from .deepseek import ToolCallResult, call_tool
from .prompts import build_extractor_messages, get_extractor_prompt_version
from .schema import EXTRACT_FUNCTION_SCHEMA, ExtractedPost
from ..logging import log


async def extract_from_text(
    cleaned_text: str,
    *,
    post_id: int | None = None,
    use_cache: bool = True,
) -> tuple[ExtractedPost, dict[str, Any]]:
    """Run Extractor on already-cleaned text.

    Returns ``(parsed, info)`` where ``info`` carries usage / cache_hit / model.
    Raises ``ValueError`` when LLM JSON cannot be parsed into ExtractedPost.
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
            parsed = ExtractedPost.model_validate(cached["arguments"])
            return parsed, {
                "cache_hit": True,
                "usage": None,
                "model": cached.get("model"),
                "version": version,
            }

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
    )

    parsed = ExtractedPost.model_validate(result.arguments)

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
