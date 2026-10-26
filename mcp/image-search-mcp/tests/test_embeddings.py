from __future__ import annotations

import numpy as np

from app.embeddings import embedding_checksum, normalize_vectors


def test_normalize_vectors_returns_unit_vectors():
    vectors = normalize_vectors(np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32))

    assert vectors.shape == (2, 2)
    assert np.allclose(np.linalg.norm(vectors[0]), 1.0)
    assert np.allclose(vectors[1], [0.0, 0.0])


def test_embedding_checksum_is_stable():
    vector = normalize_vectors(np.array([[1.0, 2.0, 3.0]], dtype=np.float32))[0]

    assert embedding_checksum(vector) == embedding_checksum(vector.copy())
    assert embedding_checksum(vector).startswith("sha256:")
