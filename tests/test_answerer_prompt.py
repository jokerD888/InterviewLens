"""Answerer prompt builder shape."""
from __future__ import annotations

from interviewlens.llm.prompts import ANSWERER_SYSTEM, build_answerer_messages


def test_messages_have_system_and_user() -> None:
    msgs = build_answerer_messages(content="什么是 Redis 分布式锁？", category="后端")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == ANSWERER_SYSTEM
    assert msgs[1]["role"] == "user"
    assert "Redis 分布式锁" in msgs[1]["content"]


def test_category_optional() -> None:
    msgs = build_answerer_messages(content="讲讲 TCP", category=None)
    assert "讲讲 TCP" in msgs[1]["content"]


def test_category_hint_in_user_message() -> None:
    msgs = build_answerer_messages(content="什么是 GIL？", category="Python")
    assert "Python" in msgs[1]["content"]
