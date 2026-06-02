"""Tests for the dedup clustering helper (pure math, no I/O)."""
from __future__ import annotations

import numpy as np

from interviewlens.aggregator.aggregator import _cluster_questions


def _q(qid: int, content: str, score: int = 50, category: str | None = None) -> dict:
    return {"id": qid, "content": content, "category": category, "quality_score": score}


def test_cluster_collapses_near_duplicates() -> None:
    qs = [_q(1, "Redis 分布式锁"), _q(2, "Redis 分布式锁实现"), _q(3, "讲讲 TCP 三次握手")]
    # craft embeddings: 1,2 are near-identical, 3 is orthogonal
    e1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    e2 = np.array([0.99, 0.01, 0.0], dtype=np.float32)
    e2 = e2 / np.linalg.norm(e2)
    e3 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    embs = {1: e1, 2: e2, 3: e3}

    clusters = _cluster_questions(qs, embs, threshold=0.9)
    assert len(clusters) == 2
    # the merged cluster should report freq=2
    by_id = {c["id"]: c for c in clusters}
    assert by_id[1]["freq"] == 2 or any(c.get("freq") == 2 for c in clusters)


def test_cluster_no_dedup_when_below_threshold() -> None:
    qs = [_q(1, "a"), _q(2, "b")]
    e1 = np.array([1.0, 0.0], dtype=np.float32)
    e2 = np.array([0.0, 1.0], dtype=np.float32)
    clusters = _cluster_questions(qs, {1: e1, 2: e2}, threshold=0.9)
    assert len(clusters) == 2
    assert all(c["freq"] == 1 for c in clusters)


def test_cluster_missing_embedding_treated_as_unique() -> None:
    qs = [_q(1, "a"), _q(2, "b")]
    clusters = _cluster_questions(qs, {}, threshold=0.9)
    assert len(clusters) == 2
    assert all(c["freq"] == 1 for c in clusters)


def test_cluster_ranks_by_freq_then_score() -> None:
    qs = [_q(1, "x", score=10), _q(2, "y", score=80), _q(3, "x2", score=20)]
    e1 = np.array([1.0, 0.0], dtype=np.float32)
    e2 = np.array([0.0, 1.0], dtype=np.float32)
    e3 = np.array([0.99, 0.01], dtype=np.float32)
    e3 = e3 / np.linalg.norm(e3)
    clusters = _cluster_questions(qs, {1: e1, 2: e2, 3: e3}, threshold=0.9)
    # First cluster should have freq=2 (1 absorbing 3), second is q2 alone
    assert clusters[0].get("freq") == 2
    assert clusters[1].get("freq") == 1
