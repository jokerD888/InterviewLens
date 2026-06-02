"""Unit tests for cache key builder. Skip the actual Redis round-trip here."""
from __future__ import annotations

from interviewlens.llm.cache import make_cache_key


def test_key_is_stable() -> None:
    a = make_cache_key(namespace="extract", payload={"text": "hi"}, version=1)
    b = make_cache_key(namespace="extract", payload={"text": "hi"}, version=1)
    assert a == b


def test_key_changes_with_version() -> None:
    a = make_cache_key(namespace="extract", payload={"text": "hi"}, version=1)
    b = make_cache_key(namespace="extract", payload={"text": "hi"}, version=2)
    assert a != b


def test_key_ignores_dict_order() -> None:
    a = make_cache_key(namespace="x", payload={"a": 1, "b": 2}, version=1)
    b = make_cache_key(namespace="x", payload={"b": 2, "a": 1}, version=1)
    assert a == b


def test_key_namespace_isolated() -> None:
    a = make_cache_key(namespace="extract", payload={"text": "hi"}, version=1)
    b = make_cache_key(namespace="summary", payload={"text": "hi"}, version=1)
    assert a != b
