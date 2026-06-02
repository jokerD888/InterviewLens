"""Smoke tests — must pass at end of D1."""
from __future__ import annotations

from interviewlens import __version__
from interviewlens.config import settings


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_settings_loaded() -> None:
    assert settings.embedding_dim == 1024
    assert settings.deepseek_base_url.startswith("http")
