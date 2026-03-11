"""EasyLCA CSV data source.

Parses easyLCA CSV exports into structured LCI data grouped by process,
with inputs and outputs separated by direction.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import pandas as pd
from openbench.core.abstractions import DataSource, RawData

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = frozenset({"Process", "Flow", "Category", "Amount", "Unit", "Direction"})


class EasyLCASource(DataSource):
    """Data source for easyLCA CSV exports.

    Expected CSV format:
        Process,Flow,Category,Amount,Unit,Direction[,Compartment,SubCompartment]

    Direction values: "Input" or "Output" (case-insensitive).

    Args:
        path: Path to the easyLCA CSV file.
        encoding: File encoding. Defaults to "utf-8".
    """

    def __init__(self, path: str | Path, encoding: str = "utf-8"):
        self._path = Path(path)
        self._encoding = encoding

    @property
    def source_type(self) -> str:
        return "easylca_csv"

    @property
    def source_id(self) -> str:
        path_hash = hashlib.md5(str(self._path.resolve()).encode()).hexdigest()[:8]
        return f"easylca_{path_hash}"

    def get_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "path": str(self._path),
            "encoding": self._encoding,
            "format": "easylca_csv",
        }
        if self._path.exists():
            meta["size_bytes"] = self._path.stat().st_size
        return meta

    def validate(self) -> bool:
        """Validate that the file exists and contains required columns."""
        if not self._path.exists():
            logger.warning("File not found: %s", self._path)
            return False

        try:
            df = pd.read_csv(self._path, encoding=self._encoding, nrows=0)
            actual_columns = set(df.columns.str.strip())
            missing = REQUIRED_COLUMNS - actual_columns
            if missing:
                logger.warning("Missing required columns: %s", missing)
                return False
            return True
        except Exception as e:
            logger.warning("Failed to validate %s: %s", self._path, e)
            return False

    def extract(self) -> RawData:
        """Extract and structure LCI data from easyLCA CSV.

        Returns:
            RawData with content as dict:
                {
                    "processes": {
                        "Process Name": {
                            "inputs": [{"flow": ..., "amount": ..., ...}],
                            "outputs": [...]
                        }
                    },
                    "summary": {"total_rows": N, "processes": [...], "categories": [...]}
                }
        """
        if not self.validate():
            raise ValueError(f"Invalid easyLCA CSV file: {self._path}")

        df = pd.read_csv(self._path, encoding=self._encoding)
        df.columns = df.columns.str.strip()

        # Normalize direction values
        df["Direction"] = df["Direction"].str.strip().str.lower()

        processes: dict[str, dict[str, list[dict[str, Any]]]] = {}
        categories: set[str] = set()

        for _, row in df.iterrows():
            process_name = str(row["Process"]).strip()
            direction = row["Direction"]

            if process_name not in processes:
                processes[process_name] = {"inputs": [], "outputs": []}

            flow_data: dict[str, Any] = {
                "flow": str(row["Flow"]).strip(),
                "category": str(row["Category"]).strip(),
                "amount": float(row["Amount"]),
                "unit": str(row["Unit"]).strip(),
            }

            # Optional columns
            if "Compartment" in df.columns and pd.notna(row.get("Compartment")):
                flow_data["compartment"] = str(row["Compartment"]).strip()
            if "SubCompartment" in df.columns and pd.notna(row.get("SubCompartment")):
                flow_data["sub_compartment"] = str(row["SubCompartment"]).strip()

            categories.add(flow_data["category"])

            if direction == "input":
                processes[process_name]["inputs"].append(flow_data)
            elif direction == "output":
                processes[process_name]["outputs"].append(flow_data)
            else:
                logger.warning("Unknown direction '%s' for flow '%s'", direction, flow_data["flow"])

        content = {
            "processes": processes,
            "summary": {
                "total_rows": len(df),
                "processes": sorted(processes.keys()),
                "categories": sorted(categories),
            },
        }

        metadata = {
            "rows_parsed": len(df),
            "process_count": len(processes),
            "categories": sorted(categories),
            "path": str(self._path),
        }

        return RawData(
            content=content,
            content_type="structured",
            metadata=metadata,
            source=self,
        )
