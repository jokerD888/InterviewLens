"""Normalizer package: entity normalisation across alias_dict + embedding + LLM."""
from .resolver import (
    EMBED_THRESHOLD_HIGH,
    EMBED_THRESHOLD_LOW,
    LLM_MIN_CONFIDENCE,
    ResolveResult,
    resolve_entity,
)

__all__ = [
    "EMBED_THRESHOLD_HIGH",
    "EMBED_THRESHOLD_LOW",
    "LLM_MIN_CONFIDENCE",
    "ResolveResult",
    "resolve_entity",
]
