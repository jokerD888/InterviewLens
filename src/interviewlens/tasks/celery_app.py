"""Celery app singleton."""
from __future__ import annotations

from celery import Celery

from ..config import settings

celery_app = Celery(
    "interviewlens",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    # bge-m3 + Playwright are slow; expand visibility timeouts
    broker_transport_options={"visibility_timeout": 60 * 30},
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,  # recycle worker after N tasks (Playwright leaks)
    task_track_started=True,
    # Hard cap per task — runaway crawls won't pin a worker forever
    task_time_limit=60 * 5,
    task_soft_time_limit=60 * 4,
)

# Auto-discover task modules
celery_app.autodiscover_tasks(["interviewlens.tasks"])
