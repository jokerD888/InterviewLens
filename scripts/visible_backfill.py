"""Visible serial harvesting; continuous mode keeps request pacing across batches."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


def parse_since(value: str) -> datetime:
    try:
        return datetime.combine(date.fromisoformat(value), time.min, ZoneInfo("Asia/Shanghai"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("since must be YYYY-MM-DD") from exc


def should_continue(report: dict) -> bool:
    return (
        report.get("status") in ("complete", "batch_limit")
        and not report.get("completed", False)
        and bool(report.get("saved") or report.get("discovered_pages"))
    )


async def run_batches(batch, *, once=False, emit=print):
    while True:
        report = await batch()
        emit("report", report)
        if once or not should_continue(report):
            return report
        # No batch sleep: the same request limiter survives into the next batch.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--listing", choices=("tab", "job"), default="tab")
    parser.add_argument("--job-id", type=int, default=-1)
    parser.add_argument("--job-level", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--since", type=parse_since, help="Campaign boundary (Beijing date); must match an existing cursor")
    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv(args.project_root / ".env", override=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from interviewlens.crawler.backfill import BackfillLimits, backfill_batch
    from interviewlens.crawler.playwright_runner import NowcoderFetcher
    from interviewlens.crawler.rate_limit import AsyncRateLimiter

    logs = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "InterviewLens" / "visible-backfill"
    logs.mkdir(parents=True, exist_ok=True)
    stem = f"batch-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}"
    log_path, result_path = logs / f"{stem}.log", logs / f"{stem}.json"
    limiter = AsyncRateLimiter(rate_per_sec=1 / 10, jitter=(1, 10))

    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        def emit(event, fields):
            line = json.dumps({"time": datetime.now().astimezone().isoformat(),
                               "event": event, **fields}, ensure_ascii=False, default=str)
            print(line, flush=True)
            log.write(line + "\n")
            if event in ("report", "error"):
                result_path.write_text(line, encoding="utf-8")

        async def batch():
            return await backfill_batch(
                limits=BackfillLimits(pages=5, cooldown=0, continuous=True, daily=None),
                listing=args.listing, job_id=args.job_id, job_level=args.job_level,
                since=args.since,
                fetcher_factory=lambda: NowcoderFetcher(limiter=limiter), progress=emit,
            )

        emit("startup", {"log": str(log_path), "once": args.once,
                         "batch": 30, "daily": "unlimited", "request_interval": "11..20s",
                         "listing": args.listing, "job_id": args.job_id,
                         "job_level": args.job_level, "since": args.since})
        try:
            report = asyncio.run(run_batches(batch, once=args.once, emit=emit))
        except KeyboardInterrupt:
            emit("error", {"reason": "user_stopped"})
            return 130
        except Exception as exc:
            # Avoid logging credential-bearing connection strings or HTTP headers.
            emit("error", {"reason": type(exc).__name__, "error_module": type(exc).__module__})
            return 1
        print("Stopped. Read the final report above before restarting.", flush=True)
        if report.get("status") not in ("complete", "batch_limit"):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
