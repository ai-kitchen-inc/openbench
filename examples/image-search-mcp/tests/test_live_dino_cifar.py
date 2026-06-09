from __future__ import annotations

import os

import pytest
from app.service import get_service


@pytest.mark.skipif(
    os.getenv("RUN_DINO_CIFAR_LIVE") != "1",
    reason="set RUN_DINO_CIFAR_LIVE=1 to download CIFAR-10/model weights",
)
def test_live_dino_cifar_small_index():
    service = get_service()

    stats = service.rebuild_index(max_items=8, batch_size=4)

    assert stats["indexed"] == 8
    assert stats["complete"] is False
    assert stats["partial"] is True
    assert stats["healthy"] is True

    result = service.search_similar_images(cifar10_test_index=0, top_k=3)

    assert result["count"] == 3
    assert result["corpus"]["complete"] is False
    assert result["corpus"]["partial"] is True
