"""Verify consecutive batches retain guardrails without long batch sleeps."""

import argparse
import importlib.util
from datetime import UTC, datetime
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
    assert runner.should_continue({"status": "complete", "saved": 30, "completed": True, "pending": 8})


def test_source_switch_retains_original_beijing_campaign_boundary():
    assert runner.parse_since("2026-07-08").astimezone(UTC) == datetime(2026, 7, 7, 16, tzinfo=UTC)
    with pytest.raises(argparse.ArgumentTypeError):
        runner.parse_since("bad-date")


async def test_partition_boundary_drains_queue_then_switches_without_resuming_list():
    plan = [{"name": "frontend", "job_id": 11201, "job_level": 2},
            {"name": "data", "job_id": 11204, "job_level": 2}]
    batch = AsyncMock(side_effect=[
        {"status": "stopped", "reason": "pagination_repeated", "pending": 2},
        {"status": "drained", "paused_reason": "pagination_repeated", "pending": 0},
        {"status": "complete", "completed": True, "pending": 0},
    ])
    result = await runner.run_partitions(batch, plan, emit=lambda *_: None)
    assert result["status"] == "partial"
    assert [row["coverage"] for row in result["partitions"]] == ["unverified", "listing_exhausted"]
    assert [(call.args[0]["job_id"], call.kwargs["pending_only"])
            for call in batch.await_args_list] == [(11201, False), (11201, True), (11204, False)]


@pytest.mark.parametrize("reason", ["http_429", "login_or_challenge", "api_rejected", "empty_detail"])
async def test_partition_plan_never_switches_sources_to_evade_site_guard(reason):
    plan = [{"name": "frontend", "job_id": 11201, "job_level": 2},
            {"name": "data", "job_id": 11204, "job_level": 2}]
    batch = AsyncMock(return_value={"status": "stopped", "reason": reason,
                                   "paused_reason": "pagination_repeated", "pending": 2})
    result = await runner.run_partitions(batch, plan, emit=lambda *_: None)
    assert result["reason"] == reason
    batch.assert_awaited_once()


def test_partition_plan_uses_verified_unique_jobs(tmp_path):
    entries = runner.load_partitions(Path(__file__).parents[1] / "data" / "crawl_partitions.json")
    assert len(entries) == 11
    invalid = tmp_path / "bad.json"
    invalid.write_text('[{"name":"x","job_id":true,"job_level":2}]', encoding="utf-8")
    with pytest.raises(ValueError):
        runner.load_partitions(invalid)
