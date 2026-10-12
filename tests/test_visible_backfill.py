"""Verify consecutive batches retain guardrails without long batch sleeps."""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from interviewlens.crawler.backfill import BackfillLimits

spec = importlib.util.spec_from_file_location(
    "visible_backfill", Path(__file__).parents[1] / "scripts" / "visible_backfill.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_continuous_mode_explicit_and_preserves_budget_caps():
    assert BackfillLimits(cooldown=0, continuous=True).daily == 100
    assert BackfillLimits(cooldown=0, continuous=True, daily=None).daily is None
    for kwargs in ({"cooldown": 0}, {"continuous": True},
                   {"cooldown": 0, "continuous": True, "daily": 101}):
        with pytest.raises(ValueError):
            BackfillLimits(**kwargs)


@pytest.mark.parametrize("reason", ["daily_limit", "paused", "locked", "stopped", "error"])
async def test_loop_stops_on_guard_or_budget(reason):
    batch = AsyncMock(side_effect=[
        {"status": "complete", "saved": 30, "today_attempts": 30},
        {"status": reason, "reason": "pagination_repeated"},
    ])
    report = await runner.run_batches(batch, emit=lambda *_: None)
    assert report["status"] == reason
    assert batch.await_count == 2


async def test_once_does_not_start_another_batch():
    batch = AsyncMock(return_value={"status": "complete", "saved": 26})
    await runner.run_batches(batch, once=True, emit=lambda *_: None)
    batch.assert_awaited_once()


def test_no_progress_or_finished_scan_stops():
    assert not runner.should_continue({"status": "complete", "saved": 0})
    assert not runner.should_continue({"status": "complete", "saved": 30, "completed": True})
    assert runner.should_continue({"status": "complete", "saved": 30, "today_attempts": 1000})
