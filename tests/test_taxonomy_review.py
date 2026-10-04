import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from interviewlens import taxonomy_review


@pytest.mark.asyncio
async def test_review_import_rejects_changed_source(tmp_path, monkeypatch):
    manifest = tmp_path / "review.jsonl"
    manifest.write_text(
        json.dumps({"post_id": 1, "approve": True, "input_hash": "stale"}), encoding="utf-8"
    )
    result = MagicMock()
    result.mappings.return_value.first.return_value = {
        "title": "后端开发",
        "cleaned_text": "新正文",
    }
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def fake_scope():
        yield session

    save = AsyncMock()
    monkeypatch.setattr(taxonomy_review, "session_scope", fake_scope)
    monkeypatch.setattr(taxonomy_review, "save_profiles", save)
    with pytest.raises(ValueError, match="changed since"):
        await taxonomy_review.import_reviews(manifest)
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_unapproved_preview_is_not_imported(tmp_path, monkeypatch):
    manifest = tmp_path / "preview.jsonl"
    manifest.write_text(json.dumps({"post_id": 1, "approve": False}), encoding="utf-8")
    session = MagicMock()
    session.execute = AsyncMock()

    @asynccontextmanager
    async def fake_scope():
        yield session

    monkeypatch.setattr(taxonomy_review, "session_scope", fake_scope)
    await taxonomy_review.import_reviews(manifest)
    session.execute.assert_not_awaited()
