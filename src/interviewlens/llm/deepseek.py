"""Async DeepSeek client wrapper around the OpenAI SDK + Langfuse trace."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import settings
from ..logging import log
from ..observability import get_langfuse


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
    return _client


@dataclass(slots=True)
class ToolCallResult:
    name: str
    arguments: dict
    raw_response: dict
    usage: dict | None
    model: str


async def call_tool(
    *,
    messages: list[dict],
    tools: list[dict],
    tool_choice: dict | str = "auto",
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    trace_name: str | None = None,
    trace_metadata: dict | None = None,
    trace: Any | None = None,
) -> ToolCallResult:
    """Call DeepSeek chat-completion with forced tool use.

    If ``trace`` is given (a Langfuse Trace), generations hang under it.
    Otherwise an ad-hoc trace is created if Langfuse is configured.
    """
    model = model or settings.deepseek_model_chat
    client = get_client()
    lf = get_langfuse()
    own_trace = False
    if trace is None and lf is not None:
        try:
            trace = lf.trace(name=trace_name or "extract", metadata=trace_metadata or {})
            own_trace = True
        except Exception as exc:  # noqa: BLE001
            log.warning("langfuse.trace_create_failed", err=str(exc))
            trace = None

    attempt_idx = 0
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=15),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    ):
        with attempt:
            attempt_idx += 1
            local_temp = temperature if attempt_idx == 1 else 0.0
            log.info(
                "llm.call",
                model=model,
                attempt=attempt_idx,
                temperature=local_temp,
                msg_count=len(messages),
            )
            generation = None
            if trace is not None:
                try:
                    generation = trace.generation(
                        name="deepseek.tool_call",
                        model=model,
                        input=messages,
                        metadata={"attempt": attempt_idx, "temperature": local_temp},
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("langfuse.gen_create_failed", err=str(exc))
                    generation = None

            resp: ChatCompletion = await client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                tool_choice=tool_choice,  # type: ignore[arg-type]
                temperature=local_temp,
                max_tokens=max_tokens,
            )

            choice = resp.choices[0]
            tool_calls = choice.message.tool_calls or []
            if not tool_calls:
                if generation:
                    try:
                        generation.end(level="ERROR", status_message="no tool call")
                    except Exception:  # noqa: BLE001
                        pass
                raise RuntimeError("LLM returned no tool call")
            tc = tool_calls[0]
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as exc:
                if generation:
                    try:
                        generation.end(
                            level="ERROR",
                            status_message=f"JSONDecodeError: {exc}",
                            output=tc.function.arguments,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                raise RuntimeError(f"Invalid JSON in tool args: {exc}") from exc

            usage = resp.usage.model_dump() if resp.usage else None
            if generation:
                try:
                    generation.end(output=args, usage=usage)
                except Exception:  # noqa: BLE001
                    pass
            if own_trace and trace is not None:
                try:
                    trace.update(output=args)
                except Exception:  # noqa: BLE001
                    pass
            log.info(
                "llm.done",
                tool=tc.function.name,
                usage=usage,
                attempts=attempt_idx,
            )
            return ToolCallResult(
                name=tc.function.name,
                arguments=args,
                raw_response=resp.model_dump(),
                usage=usage,
                model=model,
            )

    raise RuntimeError("unreachable")


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
