"""Pure scoring functions used by the pipeline and read paths.

The stable part of a post's score is its content completeness.  Freshness is
time-dependent and therefore must be calculated with an explicit reference
time when a result is ranked.  ``score_extracted`` remains as a compatibility
wrapper for callers that still need the old four-component breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

CONTENT_SCORE_VERSION = 1
FRESHNESS_POLICY_VERSION = 1


@dataclass(slots=True)
class ScorerWeights:
    quantity_max: int = 30
    quantity_per_question: int = 3   # 10 questions saturates the quantity bucket

    answers_max: int = 20
    answers_per_filled: int = 4      # 5 answer briefs saturate

    rounds_max: int = 20
    rounds_per_round: int = 7        # 3 rounds saturate

    recency_max: int = 30
    # Piecewise freshness buckets in months, descending.
    recency_table: list[tuple[int, int]] = field(
        default_factory=lambda: [
            (3, 30),    # ≤ 3 months → 30
            (6, 25),    # ≤ 6 months → 25
            (12, 15),   # ≤ 12 months → 15
            (24, 8),    # ≤ 24 months → 8
        ]
    )


@dataclass(slots=True)
class ScoreBreakdown:
    quantity: int
    answers: int
    rounds: int
    recency: int
    total: int

    def as_dict(self) -> dict[str, int]:
        return {
            "quantity": self.quantity,
            "answers": self.answers,
            "rounds": self.rounds,
            "recency": self.recency,
            "total": self.total,
        }


@dataclass(slots=True)
class ContentScoreBreakdown:
    """Stable score derived only from the extracted interview content."""

    quantity: int
    answers: int
    rounds: int
    total: int

    def as_dict(self) -> dict[str, int]:
        return {
            "quantity": self.quantity,
            "answers": self.answers,
            "rounds": self.rounds,
            "total": self.total,
        }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def score_content(
    extracted: dict[str, Any] | None,
    *,
    weights: ScorerWeights | None = None,
) -> ContentScoreBreakdown:
    """Compute the stable 0..70 content-completeness score.

    This function intentionally does not accept ``posted_at``.  It can be
    safely persisted and rescored without depending on the wall clock.
    """
    w = weights or ScorerWeights()
    extracted = extracted or {}
    rounds = extracted.get("rounds") or []

    n_questions = sum(len(r.get("questions") or []) for r in rounds)
    n_with_answer = sum(
        1
        for r in rounds
        for q in (r.get("questions") or [])
        if (q.get("answer_brief") or "").strip()
    )
    n_rounds = len(rounds)

    quantity = min(n_questions * w.quantity_per_question, w.quantity_max)
    answers = min(n_with_answer * w.answers_per_filled, w.answers_max)
    rounds_score = min(n_rounds * w.rounds_per_round, w.rounds_max)
    total = quantity + answers + rounds_score
    return ContentScoreBreakdown(
        quantity=quantity,
        answers=answers,
        rounds=rounds_score,
        total=total,
    )


def score_freshness(
    posted_at: datetime | None,
    *,
    weights: ScorerWeights | None = None,
    as_of: datetime | None = None,
) -> int:
    """Compute the dynamic 0..30 freshness score from ``posted_at``.

    ``as_of`` is explicit so one request can use one consistent time snapshot
    and tests do not depend on the actual wall clock.  Unknown dates receive
    zero; ``fetched_at`` must never be substituted for ``posted_at``.
    """
    if posted_at is None:
        return 0

    w = weights or ScorerWeights()
    ref = _as_utc(as_of or _now_utc())
    posted = _as_utc(posted_at)
    days = max((ref - posted).total_seconds() / 86400, 0)
    months = days / 30
    for cutoff, value in w.recency_table:
        if months <= cutoff:
            return value
    return 0


def ranking_score(
    content_score: int,
    freshness_score: int,
    *,
    weights: ScorerWeights | None = None,
) -> int:
    """Combine stable content and dynamic freshness for recommendation views."""
    w = weights or ScorerWeights()
    return min(content_score + freshness_score, w.quantity_max + w.answers_max + w.rounds_max + w.recency_max)


def score_extracted(
    extracted: dict[str, Any] | None,
    *,
    posted_at: datetime | None = None,
    weights: ScorerWeights | None = None,
    now: datetime | None = None,
) -> ScoreBreakdown:
    """Compatibility wrapper for the former four-component score."""
    w = weights or ScorerWeights()
    content = score_content(extracted, weights=w)
    recency = score_freshness(posted_at, weights=w, as_of=now)
    total = ranking_score(content.total, recency, weights=w)
    return ScoreBreakdown(
        quantity=content.quantity,
        answers=content.answers,
        rounds=content.rounds,
        recency=recency,
        total=total,
    )


def freshness_case_sql(*, posted_at_sql: str = "po.posted_at", as_of_param: str = ":as_of") -> str:
    """Return the PostgreSQL CASE expression used by dynamic ranking queries."""
    return f"""CASE
        WHEN {posted_at_sql} IS NULL THEN 0
        WHEN {posted_at_sql} >= {as_of_param} - INTERVAL '90 days' THEN 30
        WHEN {posted_at_sql} >= {as_of_param} - INTERVAL '180 days' THEN 25
        WHEN {posted_at_sql} >= {as_of_param} - INTERVAL '360 days' THEN 15
        WHEN {posted_at_sql} >= {as_of_param} - INTERVAL '720 days' THEN 8
        ELSE 0
    END"""
