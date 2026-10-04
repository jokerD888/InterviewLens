"""The actual worker initialization hook must reset inherited DB/loop state."""

from unittest.mock import MagicMock

from interviewlens.db import session
from interviewlens.tasks import pipeline


def test_worker_initialization_resets_inherited_state(monkeypatch):
    reset = MagicMock()
    monkeypatch.setattr(session, "reset_engine", reset)
    monkeypatch.setattr(pipeline.BackgroundLoopWorker, "_instance", object())
    pipeline._reset_worker_loop_and_db()
    reset.assert_called_once_with()
    assert pipeline.BackgroundLoopWorker._instance is None
