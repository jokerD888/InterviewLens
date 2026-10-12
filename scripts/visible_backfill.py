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


def load_partitions(path: Path) -> list[dict]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise ValueError("partition plan must contain 1..32 jobs")
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
                or not entry["name"].strip()
                or type(entry.get("job_id")) is not int or entry["job_id"] <= 0
                or type(entry.get("job_level")) is not int or entry["job_level"] not in (2, 3)):
            raise ValueError("invalid partition")
        key = (entry["job_id"], entry["job_level"])
        if key in seen:
            raise ValueError("duplicate partition")
        seen.add(key)
    return entries


async def run_partitions(batch, partitions, *, once=False, emit=print):
    outcomes = []
    for partition in partitions:
        drain = False
        emit("partition_start", partition)
        while True:
            report = await batch(partition, pending_only=drain)
            emit("report", {**report, "partition": partition["name"]})
            if once:
                return report
            boundary = (report.get("reason") or report.get("paused_reason")) == "pagination_repeated"
            if report.get("status") in ("stopped", "paused", "drained") and boundary:
                if report.get("pending", 0):
                    drain = True
                    continue
                outcomes.append({**partition, "coverage": "unverified", "reason": "pagination_repeated"})
                emit("partition_boundary", outcomes[-1])
                break
            if report.get("status") == "drained":
                # An unexpected draining outcome must not resume list requests.
                return report
            if should_continue(report):
                continue
            if report.get("status") == "complete" and report.get("completed") and not report.get("pending"):
                outcomes.append({**partition, "coverage": "listing_exhausted"})
                break
            return report  # Login, 429, errors, lock contention stop the WHOLE plan.
    final = {"status": "partial" if any(row["coverage"] == "unverified" for row in outcomes) else "complete",
             "partitions": outcomes}
    emit("report", final)
    return final


def should_continue(report: dict) -> bool:
    return (
        report.get("status") in ("complete", "batch_limit")
        and (not report.get("completed", False) or report.get("pending", 0) > 0)
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
    parser.add_argument("--partitioned", action="store_true", help="Serially scan the verified development job partitions")
    args = parser.parse_args()
    if args.partitioned and args.since is None:
        parser.error("--partitioned requires --since to preserve the historical campaign boundary")
    partitions = load_partitions(Path(__file__).resolve().parents[1] / "data" / "crawl_partitions.json") if args.partitioned else None
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

        async def batch(partition=None, *, pending_only=False):
            job_id = partition["job_id"] if partition else args.job_id
            level = partition["job_level"] if partition else args.job_level
            def progress(event, fields):
                emit(event, {**fields, "job_id": job_id, "job_level": level,
                             "partition": partition["name"] if partition else None})
            return await backfill_batch(
                limits=BackfillLimits(pages=5, cooldown=0, continuous=True, daily=None),
                listing="job" if partition else args.listing, job_id=job_id, job_level=level,
                since=args.since,
                pending_only=pending_only,
                fetcher_factory=lambda: NowcoderFetcher(limiter=limiter), progress=progress,
            )

        emit("startup", {"log": str(log_path), "once": args.once,
                         "batch": 30, "daily": "unlimited", "request_interval": "11..20s",
                         "listing": args.listing, "job_id": args.job_id,
                         "job_level": args.job_level, "since": args.since, "partitioned": args.partitioned})
        try:
            report = asyncio.run(run_partitions(batch, partitions, once=args.once, emit=emit)
                                 if partitions else run_batches(batch, once=args.once, emit=emit))
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
