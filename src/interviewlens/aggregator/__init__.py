"""Aggregator package."""
from .aggregator import (
    AggregateOutcome,
    DEFAULT_TOP_N,
    DUP_SIM_THRESHOLD,
    MIN_QUALITY_SCORE,
    aggregate_all,
    aggregate_one,
)

__all__ = [
    "AggregateOutcome",
    "DEFAULT_TOP_N",
    "DUP_SIM_THRESHOLD",
    "MIN_QUALITY_SCORE",
    "aggregate_all",
    "aggregate_one",
]
