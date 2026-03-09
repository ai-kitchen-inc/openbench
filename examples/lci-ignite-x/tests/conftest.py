"""Shared test fixtures for LCI Ignite X."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def easylca_sample_path() -> Path:
    return FIXTURES_DIR / "easylca_sample.csv"


@pytest.fixture
def easylca_minimal_path() -> Path:
    return FIXTURES_DIR / "easylca_minimal.csv"


@pytest.fixture
def easylca_malformed_path() -> Path:
    return FIXTURES_DIR / "easylca_malformed.csv"


@pytest.fixture
def simapro_sample_path() -> Path:
    return FIXTURES_DIR / "simapro_sample.csv"


@pytest.fixture
def simapro_process_path() -> Path:
    return FIXTURES_DIR / "simapro_process.csv"


@pytest.fixture
def simapro_malformed_path() -> Path:
    return FIXTURES_DIR / "simapro_malformed.csv"


def make_docs(processes: dict | None = None) -> dict:
    """Create mock structured LCI data for testing.

    Args:
        processes: Optional custom process data. If None, uses a default
            single-process example.

    Returns:
        Dict matching EasyLCASource extract() output format.
    """
    if processes is None:
        processes = {
            "Test Process": {
                "inputs": [
                    {"flow": "Water", "category": "Resources", "amount": 100.0, "unit": "L"},
                    {"flow": "Electricity", "category": "Energy", "amount": 50.0, "unit": "kWh"},
                ],
                "outputs": [
                    {"flow": "CO2", "category": "Emissions", "amount": 75.0, "unit": "kg"},
                    {"flow": "Product A", "category": "Products", "amount": 1.0, "unit": "kg"},
                ],
            }
        }

    categories = set()
    total_flows = 0
    for proc in processes.values():
        for flow in proc["inputs"] + proc["outputs"]:
            categories.add(flow["category"])
            total_flows += 1

    return {
        "processes": processes,
        "summary": {
            "total_rows": total_flows,
            "processes": sorted(processes.keys()),
            "categories": sorted(categories),
        },
    }


def make_attachment(file_path: str = "/tmp/test.csv", mime_type: str = "text/csv") -> dict:
    """Create a mock attachment dict for testing.

    Args:
        file_path: Path to the file.
        mime_type: MIME type of the attachment.

    Returns:
        Dict matching ChatSession Attachment format.
    """
    return {
        "file_path": file_path,
        "mime_type": mime_type,
        "filename": Path(file_path).name,
    }
