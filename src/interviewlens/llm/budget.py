"""Cross-process concurrency and conservative daily token reservation.

Redis unavailability fails closed. Ambiguous transport failures retain their
reservation; only a provider usage response releases unused tokens.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from redis.exceptions import RedisError
from datetime import UTC, datetime, timedelta

from ..config import settings
from ..observability import get_redis, incr_tokens
from ..logging import log


class LLMLimitError(RuntimeError):
    pass


async def guarded_create(create, **kwargs):
    r = get_redis()
    day = (datetime.now(UTC) + timedelta(hours=8)).strftime("%Y%m%d")
    budget_key, slots_key = f"il:llm:budget:{day}", "il:llm:slots"
    slot = uuid.uuid4().hex
    input_key = (
        "il:llm:inflight:"
        + hashlib.sha256(
            json.dumps(kwargs, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    )
    # UTF-8 bytes are a conservative prompt token bound, including tool schemas.
    reserved = (
        len(
            json.dumps(
                {"messages": kwargs.get("messages"), "tools": kwargs.get("tools")},
                ensure_ascii=False,
            ).encode()
        )
        + kwargs.get("max_tokens", 4096)
        + 256
    )
    try:
        granted = await r.eval(
            """
        local t=redis.call('TIME')
        local now=tonumber(t[1])
        redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
        if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[3]) then return -1 end
        redis.call('ZREMRANGEBYSCORE',KEYS[4],'-inf',now-60)
        if redis.call('ZCARD',KEYS[4]) >= tonumber(ARGV[5]) then return -4 end
        local used=tonumber(redis.call('GET',KEYS[1]) or '0')
        if used+tonumber(ARGV[1]) > tonumber(ARGV[2]) then return -2 end
        if not redis.call('SET',KEYS[3],ARGV[4],'NX','EX',120) then return -3 end
        redis.call('INCRBY',KEYS[1],ARGV[1])
        redis.call('EXPIRE',KEYS[1],172800)
        redis.call('ZADD',KEYS[2],now+120,ARGV[4])
        redis.call('EXPIRE',KEYS[2],180)
        redis.call('ZADD',KEYS[4],now,ARGV[4])
        redis.call('EXPIRE',KEYS[4],120)
        return 1
    """,
            4,
            budget_key,
            slots_key,
            input_key,
            "il:llm:requests",
            reserved,
            settings.llm_daily_token_budget,
            settings.llm_concurrency,
            slot,
            settings.llm_requests_per_minute,
        )
    except RedisError as exc:
        raise LLMLimitError("LLM quota store unavailable") from exc
    if granted != 1:
        reasons = {
            -1: "LLM concurrency limit reached",
            -2: "LLM daily token budget exhausted",
            -3: "Equivalent generation is already running",
            -4: "LLM request rate limit reached",
        }
        raise LLMLimitError(reasons.get(granted, "LLM reservation failed"))
    try:
        response = await create(**kwargs)
        if response.usage:
            usage = response.usage.model_dump()
            prompt, completion = (
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
            )
            await incr_tokens(prompt=prompt, completion=completion)
            actual = prompt + completion
            try:
                await r.incrby(budget_key, actual - reserved)
            except RedisError:
                # Keep the conservative reservation; do not lose a paid answer.
                log.warning("llm.budget_reconcile_failed", exc_info=True)
        return response
    finally:
        try:
            await r.zrem(slots_key, slot)
            await r.eval(
                """
            if redis.call('GET',KEYS[1]) == ARGV[1] then redis.call('DEL',KEYS[1]) end
        """,
                1,
                input_key,
                slot,
            )
        except RedisError:
            log.warning("llm.slot_release_failed", exc_info=True)
