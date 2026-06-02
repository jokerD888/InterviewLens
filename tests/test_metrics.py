"""Tests for MetricsSnapshot derived properties (no Redis needed)."""
from __future__ import annotations

from interviewlens.observability import MetricsSnapshot


def test_hit_rate_with_data() -> None:
    s = MetricsSnapshot(
        cache_hit=80,
        cache_miss=20,
        tokens_prompt=10_000,
        tokens_completion=4_000,
        node_runs={"crawler": 100, "extractor": 100},
        node_avg_ms={"crawler": 1500.0, "extractor": 4000.0},
    )
    assert s.cache_total == 100
    assert s.cache_hit_rate == 0.8
    assert s.tokens_total == 14_000


def test_hit_rate_no_data() -> None:
    s = MetricsSnapshot(0, 0, 0, 0, {}, {})
    assert s.cache_total == 0
    assert s.cache_hit_rate == 0.0
    assert s.estimated_cost_cny() == 0.0


def test_cost_formula() -> None:
    s = MetricsSnapshot(
        cache_hit=0,
        cache_miss=0,
        tokens_prompt=1_000_000,
        tokens_completion=500_000,
        node_runs={},
        node_avg_ms={},
    )
    # default DeepSeek pricing: 1元 in, 2元 out per million
    assert s.estimated_cost_cny() == 1.0 * 1.0 + 0.5 * 2.0  # 2.0


def test_custom_pricing() -> None:
    s = MetricsSnapshot(0, 0, 2_000_000, 1_000_000, {}, {})
    assert s.estimated_cost_cny(price_in_per_million=0.5, price_out_per_million=1.5) == (
        2.0 * 0.5 + 1.0 * 1.5
    )
