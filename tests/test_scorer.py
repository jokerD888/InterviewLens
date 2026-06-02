"""Tests for the four-component quality scorer (pure functions)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from interviewlens.scoring import score_extracted


def _post(rounds: list[dict]) -> dict:
    return {"rounds": rounds}


def _q(content: str = "题目", answer: str | None = None) -> dict:
    return {"content": content, "answer_brief": answer}


NOW = datetime(2026, 6, 2, tzinfo=timezone.utc)


def test_water_post_low_score() -> None:
    """Water post: 1 round, 2 questions, no answers, no date."""
    extracted = _post([{"round_no": 1, "questions": [_q(), _q()]}])
    br = score_extracted(extracted, posted_at=None, now=NOW)
    # quantity 2*3=6, answers 0, rounds 1*7=7, recency 0
    assert br.quantity == 6
    assert br.answers == 0
    assert br.rounds == 7
    assert br.recency == 0
    assert br.total == 13


def test_hardcore_post_high_score() -> None:
    """Hardcore: 4 rounds, 12 questions with answers, recent."""
    rounds = [
        {"round_no": i, "questions": [_q(answer="ans") for _ in range(3)]}
        for i in range(1, 5)
    ]
    extracted = _post(rounds)
    posted = NOW - timedelta(days=30)
    br = score_extracted(extracted, posted_at=posted, now=NOW)
    # quantity 12*3=36 → cap 30
    # answers 12*4=48 → cap 20
    # rounds 4*7=28 → cap 20
    # recency 30 (≤3 months)
    assert br.quantity == 30
    assert br.answers == 20
    assert br.rounds == 20
    assert br.recency == 30
    assert br.total == 100


def test_old_post_recency_decay() -> None:
    extracted = _post([{"round_no": 1, "questions": [_q()]}])
    br_recent = score_extracted(extracted, posted_at=NOW - timedelta(days=60), now=NOW)
    br_old = score_extracted(extracted, posted_at=NOW - timedelta(days=400), now=NOW)
    assert br_recent.recency > br_old.recency
    # >24 months → recency 0
    br_ancient = score_extracted(extracted, posted_at=NOW - timedelta(days=900), now=NOW)
    assert br_ancient.recency == 0


def test_total_capped_at_100() -> None:
    rounds = [{"round_no": i, "questions": [_q(answer="a")] * 50} for i in range(1, 10)]
    br = score_extracted(_post(rounds), posted_at=NOW, now=NOW)
    assert br.total == 100


def test_empty_extracted() -> None:
    br = score_extracted(None, posted_at=NOW, now=NOW)
    # all components 0 except recency
    assert br.quantity == 0
    assert br.answers == 0
    assert br.rounds == 0
    assert br.recency == 30


def test_naive_datetime_treated_as_utc() -> None:
    extracted = _post([{"round_no": 1, "questions": [_q()]}])
    posted_naive = (NOW - timedelta(days=10)).replace(tzinfo=None)
    br = score_extracted(extracted, posted_at=posted_naive, now=NOW)
    assert br.recency == 30  # ≤ 3 months
