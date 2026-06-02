"""Pure-math tests for embedding helpers (no model load)."""
from __future__ import annotations

import numpy as np

from interviewlens.embedding import cosine, cosine_matrix


def test_cosine_normalised_identical() -> None:
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert abs(cosine(a, a) - 1.0) < 1e-6


def test_cosine_orthogonal() -> None:
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert abs(cosine(a, b)) < 1e-6


def test_cosine_matrix_shape() -> None:
    q = np.eye(2, 4, dtype=np.float32)
    g = np.eye(3, 4, dtype=np.float32)
    m = cosine_matrix(q, g)
    assert m.shape == (2, 3)
    # rows 0,1 of q match rows 0,1 of g exactly → diag-like
    assert abs(m[0, 0] - 1.0) < 1e-6
    assert abs(m[1, 1] - 1.0) < 1e-6
    assert abs(m[0, 1]) < 1e-6


def test_cosine_matrix_empty() -> None:
    q = np.zeros((0, 4), dtype=np.float32)
    g = np.eye(3, 4, dtype=np.float32)
    m = cosine_matrix(q, g)
    assert m.shape == (0, 3)
