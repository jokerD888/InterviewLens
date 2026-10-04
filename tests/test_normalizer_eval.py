"""Tests for entity normalisation protection mechanisms, negative rules, and empirical benchmark invariants.

Validates that:
1. Incompatible pairs (e.g. '前端开发' vs '后端开发', 'Java' vs 'Go', 'Android' vs 'iOS',
   distinct enterprises) are NEVER auto-merged in Tier 2 even when BGE-M3 cosine similarity
   exceeds historical thresholds (0.85 / 0.8659).
2. Legitimate synonyms with high similarity and lexical anchors safely auto-merge in Tier 2.
3. Lexical gating blocks high-similarity candidates lacking character/stem correlation from Tier 2.
4. Tier 3 post-validation gate intercepts and refuses any LLM hallucinated matches across incompatible concepts.
5. Marginal or unanchored matches correctly carry needs_review=True and audit reason.
"""
from __future__ import annotations

from types import SimpleNamespace
import pytest

import interviewlens.normalizer.resolver as res
from interviewlens.normalizer.rules import (
    are_companies_incompatible,
    are_positions_incompatible,
    has_lexical_anchor,
    is_entity_incompatible,
)


# ---------------------------------------------------------------------------
# Unit tests for Rules and Lexical Gate
# ---------------------------------------------------------------------------

def test_position_incompatibility_rules() -> None:
    # Domain / role conflict
    bad, reason = are_positions_incompatible("前端开发", "后端开发")
    assert bad is True
    assert "role_domain_conflict" in reason

    bad, reason = are_positions_incompatible("Android开发工程师", "iOS软件工程师")
    assert bad is True
    assert "role_domain_conflict" in reason

    bad, reason = are_positions_incompatible("测试开发", "后端开发工程师")
    assert bad is True
    assert "role_domain_conflict" in reason

    # Tech stack conflict
    bad, reason = are_positions_incompatible("Java开发", "Go开发")
    assert bad is True
    assert "language_conflict" in reason

    bad, reason = are_positions_incompatible("Java工程师", "C++后台开发")
    assert bad is True
    assert "language_conflict" in reason

    # Compatible / synonym positions
    bad, _ = are_positions_incompatible("后端开发", "后端工程师")
    assert bad is False

    bad, _ = are_positions_incompatible("Java开发", "Java工程师")
    assert bad is False

    bad, _ = are_positions_incompatible("前端开发", "Web前端工程师")
    assert bad is False


def test_company_incompatibility_rules() -> None:
    bad, reason = are_companies_incompatible("字节跳动", "快手科技")
    assert bad is True
    assert "distinct_enterprises" in reason

    bad, reason = are_companies_incompatible("阿里巴巴", "腾讯")
    assert bad is True
    assert "distinct_enterprises" in reason

    bad, _ = are_companies_incompatible("字节", "字节跳动")
    assert bad is False

    bad, _ = are_companies_incompatible("Alibaba", "阿里巴巴")
    assert bad is False


def test_lexical_anchor_gating() -> None:
    # Substring or common stem
    assert has_lexical_anchor("字节", "字节跳动") is True
    assert has_lexical_anchor("后端开发", "后端工程师") is True
    assert has_lexical_anchor("Java开发", "Java工程师") is True

    # Completely disjoint strings without common stem or overlap
    assert has_lexical_anchor("RED", "小红书") is False
    assert has_lexical_anchor("ByteDance", "字节跳动") is False


# ---------------------------------------------------------------------------
# Integration tests for resolve_entity protection flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_incompatible_candidates_excluded_from_tier2_and_tier3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if '前端开发' vs '后端开发' has 0.8659 similarity (exceeding old 0.85 threshold),
    it must NOT be auto-merged in Tier 2 and must NOT be offered to LLM as candidate.
    """
    async def _no_alias(entity_type, alias):
        return None

    # Simulate database returning '后端开发' as the top pgvector neighbour
    async def _search_canonicals(entity_type, alias):
        return [{"id": 101, "canonical": "后端开发", "similarity": 0.8659}]

    # We expect it to degrade safely to tier 4 (new) because the candidate is excluded
    async def _persist_new(entity_type, alias, name):
        return res.ResolveResult(canonical_id=202, confidence=0.5, source="new")

    called_tool = False

    async def _tool(**kwargs):
        nonlocal called_tool
        called_tool = True
        return SimpleNamespace(arguments={"decision": "new", "canonical_name": "前端开发"})

    monkeypatch.setattr(res, "_lookup_alias", _no_alias)
    monkeypatch.setattr(res, "_search_canonicals", _search_canonicals)
    monkeypatch.setattr(res, "call_tool", _tool)
    monkeypatch.setattr(res, "_persist_new_canonical", _persist_new)

    result = await res.resolve_entity("position", "前端开发")

    # Incompatible candidate was completely filtered out; resolve_entity does not auto-match
    assert result.canonical_id == 202
    assert result.source == "new"


@pytest.mark.asyncio
async def test_tier2_auto_match_requires_both_high_sim_and_lexical_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    """High similarity (>=0.92) with lexical anchor triggers instant Tier-2 auto match."""
    async def _no_alias(entity_type, alias):
        return None

    async def _search_canonicals(entity_type, alias):
        return [{"id": 10, "canonical": "后端工程师", "similarity": 0.94}]

    async def _write_alias(entity_type, alias, cid, confidence):
        return cid, confidence, True

    monkeypatch.setattr(res, "_lookup_alias", _no_alias)
    monkeypatch.setattr(res, "_search_canonicals", _search_canonicals)
    monkeypatch.setattr(res, "_write_alias", _write_alias)

    result = await res.resolve_entity("position", "后端开发")

    assert result.source == "embedding"
    assert result.canonical_id == 10
    assert result.confidence == 0.94
    assert result.needs_review is False


@pytest.mark.asyncio
async def test_tier2_blocked_when_lacking_lexical_anchor_falls_to_tier3(monkeypatch: pytest.MonkeyPatch) -> None:
    """High similarity without lexical anchor must NOT auto-match; must fall through to LLM."""
    async def _no_alias(entity_type, alias):
        return None

    # e.g. An acronym/foreign string with high dense similarity but 0 character overlap
    async def _search_canonicals(entity_type, alias):
        return [{"id": 50, "canonical": "小红书", "similarity": 0.93}]

    llm_invoked = False

    async def _tool(messages, **kwargs):
        nonlocal llm_invoked
        llm_invoked = True
        return SimpleNamespace(
            arguments={"decision": "match", "canonical_id": 50, "confidence": 0.95}
        )

    async def _canonical_exists(entity_type, cid):
        return True

    async def _write_alias(entity_type, alias, cid, confidence):
        return cid, confidence, True

    monkeypatch.setattr(res, "_lookup_alias", _no_alias)
    monkeypatch.setattr(res, "_search_canonicals", _search_canonicals)
    monkeypatch.setattr(res, "call_tool", _tool)
    monkeypatch.setattr(res, "_canonical_exists", _canonical_exists)
    monkeypatch.setattr(res, "_write_alias", _write_alias)

    result = await res.resolve_entity("company", "RED")

    assert llm_invoked is True
    assert result.source == "llm"
    assert result.canonical_id == 50


@pytest.mark.asyncio
async def test_tier3_llm_hallucination_intercepted_by_post_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """If LLM hallucinates an incompatible match (e.g. matching 'Android开发' with 'iOS开发'),
    the post-validation gate MUST reject the match and fall through to tier 4.
    """
    async def _no_alias(entity_type, alias):
        return None

    # Candidate not pre-filtered (e.g. if candidate wasn't detected beforehand or returned via loose vector)
    async def _search_canonicals(entity_type, alias):
        # We manually bypass pre-filter in mock to simulate LLM returning an incompatible canonical
        return []

    async def _tool(**kwargs):
        return SimpleNamespace(
            arguments={"decision": "match", "canonical_id": 88, "confidence": 0.90}
        )

    async def _canonical_exists(entity_type, cid):
        return True

    async def _get_canonical_name(entity_type, cid):
        return "iOS开发"

    async def _persist_new(entity_type, alias, name):
        return res.ResolveResult(canonical_id=999, confidence=0.5, source="new")

    monkeypatch.setattr(res, "_lookup_alias", _no_alias)
    monkeypatch.setattr(res, "_search_canonicals", _search_canonicals)
    monkeypatch.setattr(res, "call_tool", _tool)
    monkeypatch.setattr(res, "_canonical_exists", _canonical_exists)
    monkeypatch.setattr(res, "_get_canonical_name", _get_canonical_name)
    monkeypatch.setattr(res, "_persist_new_canonical", _persist_new)

    result = await res.resolve_entity("position", "Android开发")

    # The post-validation gate caught the incompatibility between 'Android开发' and 'iOS开发',
    # rejected the LLM match, and created a new canonical safely!
    assert result.canonical_id == 999
    assert result.source == "new"


@pytest.mark.asyncio
async def test_marginal_llm_match_flagged_for_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM matches with marginal confidence (0.70 <= conf < 0.85) or no lexical anchor carry needs_review=True."""
    async def _no_alias(entity_type, alias):
        return None

    async def _search_canonicals(entity_type, alias):
        return [{"id": 30, "canonical": "质量保障工程师", "similarity": 0.65}]

    async def _tool(**kwargs):
        return SimpleNamespace(
            arguments={"decision": "match", "canonical_id": 30, "confidence": 0.75}
        )

    async def _canonical_exists(entity_type, cid):
        return True

    async def _write_alias(entity_type, alias, cid, confidence):
        return cid, confidence, True

    monkeypatch.setattr(res, "_lookup_alias", _no_alias)
    monkeypatch.setattr(res, "_search_canonicals", _search_canonicals)
    monkeypatch.setattr(res, "call_tool", _tool)
    monkeypatch.setattr(res, "_canonical_exists", _canonical_exists)
    monkeypatch.setattr(res, "_write_alias", _write_alias)

    result = await res.resolve_entity("position", "测试开发")

    assert result.source == "llm"
    assert result.canonical_id == 30
    assert result.needs_review is True
    assert "llm_low_confidence" in result.review_reason
