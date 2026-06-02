"""Quality scorer for posts. Pure function — no I/O.

Score = quantity(30) + answers(20) + rounds(20) + recency(30)  →  0..100
Weights are tunable through ``ScorerWeights`` and persisted alongside the score
so we can A/B different schemes later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class ScorerWeights:
    quantity_max: int = 30
    quantity_per_question: int = 3   # 10 questions saturates the quantity bucket

    answers_max: int = 20
    answers_per_filled: int = 4      # 5 answer briefs saturate

    rounds_max: int = 20
    rounds_per_round: int = 7        # 3 rounds saturate

    recency_max: int = 30
    # half-life buckets in months, descending
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def score_extracted(
    extracted: dict[str, Any] | None,
    *,
    posted_at: datetime | None = None,
    weights: ScorerWeights | None = None,
    now: datetime | None = None,
) -> ScoreBreakdown:
    """Compute the four-component quality score from an Extractor output.

    ``extracted`` is the JSON dict shape produced by Extractor (``ExtractedPost.model_dump()``).
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

    recency = 0
    if posted_at is not None:
        ref = now or _now_utc()
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        days = (ref - posted_at).days
        months = days / 30 if days > 0 else 0
        for cutoff, value in w.recency_table:
            if months <= cutoff:
                recency = value
                break
        # else: leave recency at 0 — older than the last bucket
    # If posted_at unknown we award 0; harsh on purpose so that posts without
    # any date metadata don't outrank dated ones.

    total = min(quantity + answers + rounds_score + recency, 100)
    return ScoreBreakdown(
        quantity=quantity,
        answers=answers,
        rounds=rounds_score,
        recency=recency,
        total=total,
    )
