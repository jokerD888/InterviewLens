"""Tests for Aggregator output parsing and bounded corrective retries."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from interviewlens.aggregator import aggregator


def test_input_fingerprint_is_stable_and_changes_with_content() -> None:
    questions = [
        {
            "id": 1,
            "content": "Redis 分布式锁怎么实现？",
            "category": "数据库",
            "content_score": 60,
        }
    ]
    kwargs = {
        "questions": questions,
        "period": "2026Q3",
        "top_n": 100,
        "min_quality": 30,
        "dedup_threshold": 0.92,
    }
    first = aggregator._build_input_fingerprint(**kwargs)
    assert first == aggregator._build_input_fingerprint(**kwargs)

    changed = [dict(questions[0], content="Redis 分布式锁如何续期？")]
    changed_kwargs = {**kwargs, "questions": changed}
    assert first != aggregator._build_input_fingerprint(**changed_kwargs)


def _valid_payload() -> dict:
    return {
        "high_frequency_topics": [
            {
                "topic": "Redis 分布式锁",
                "frequency": 2,
                "sample_questions": ["Redis 分布式锁怎么实现？"],
            }
        ],
        "focus_areas": ["分布式锁实现与失效处理"],
        "edge_cases": [
            {"topic": "锁续期", "questions": ["Redis 分布式锁怎么实现？"]}
        ],
        "prep_advice": ["准备加锁、续期和故障恢复的完整回答"],
    }


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
    )


class _FakeCompletions:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _fake_client(responses: list):
    completions = _FakeCompletions(responses)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def test_parse_aggregator_output_repairs_json_and_checks_source_questions() -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False).replace(']}', '],}')
    result = aggregator._parse_aggregator_output(
        payload,
        questions=[{"content": "Redis 分布式锁怎么实现？"}],
    )
    assert result.high_frequency_topics[0].frequency == 2


def test_parse_aggregator_output_rejects_unknown_question() -> None:
    payload = _valid_payload()
    payload["high_frequency_topics"][0]["sample_questions"] = ["模型编造的问题"]
    with pytest.raises(aggregator.AggregatorOutputError, match="not present"):
        aggregator._parse_aggregator_output(
            json.dumps(payload), questions=[{"content": "真实题目"}]
        )


@pytest.mark.asyncio
async def test_summarise_retries_empty_output_with_corrective_prompt(monkeypatch) -> None:
    client, completions = _fake_client(
        [_response(""), _response(json.dumps(_valid_payload(), ensure_ascii=False))]
    )
    monkeypatch.setattr(aggregator, "get_client", lambda: client)

    markdown, usage = await aggregator._summarise(
        company="示例公司",
        position="后端",
        period="2026Q3",
        questions=[{"content": "Redis 分布式锁怎么实现？", "freq": 2}],
    )

    assert usage is None
    assert "高频考点" in markdown
    assert len(completions.calls) == 2
    assert completions.calls[0]["temperature"] == 0.3
    assert completions.calls[1]["temperature"] == 0.0
    assert "上一次输出未通过校验" in completions.calls[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_summarise_fails_after_one_corrective_attempt(monkeypatch) -> None:
    client, completions = _fake_client([_response("{}"), _response("{}")])
    monkeypatch.setattr(aggregator, "get_client", lambda: client)

    with pytest.raises(aggregator.AggregatorOutputError, match="schema validation"):
        await aggregator._summarise(
            company="示例公司",
            position="后端",
            period="2026Q3",
            questions=[{"content": "真实题目", "freq": 1}],
        )

    assert len(completions.calls) == 2
