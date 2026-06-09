from __future__ import annotations

import numpy as np
import pytest

from app.vector_index import VectorIndex


def _make_index(tmp_path):
    try:
        return VectorIndex(tmp_path / "index", backend="auto")
    except ImportError as exc:
        pytest.skip(f"no vector backend installed: {exc}")


def test_vector_index_add_search_persist_reload_remove(tmp_path):
    index = _make_index(tmp_path)
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    metadata = [
        {"image_id": "a", "class_name": "airplane"},
        {"image_id": "b", "class_name": "truck"},
    ]

    index.add(vectors, metadata)
    hits = index.search(np.array([1.0, 0.0], dtype=np.float32), top_k=2)

    assert hits[0].metadata["image_id"] == "a"
    assert hits[0].score > hits[1].score

    reloaded = VectorIndex(tmp_path / "index", backend=index.backend)
    assert reloaded.count == 2
    assert (
        reloaded.search(np.array([0.0, 1.0], dtype=np.float32), top_k=1)[0].metadata["image_id"]
        == "b"
    )

    assert reloaded.remove("b") is True
    assert reloaded.count == 1
    assert reloaded.remove("missing") is False


def test_empty_vector_index_reports_actionable_error(tmp_path):
    index = _make_index(tmp_path)

    with pytest.raises(ValueError, match="Index is empty"):
        index.search(np.array([1.0, 0.0], dtype=np.float32), top_k=1)
