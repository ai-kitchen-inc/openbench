"""SimaPro CSV data source.

Parses SimaPro CSV exports using block-based parsing. SimaPro CSVs use
section markers (e.g., "Products", "Materials/fuels", "Emissions to air")
to delimit different data blocks within a process.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from openbench.core.abstractions import DataSource, RawData

logger = logging.getLogger(__name__)

# Section markers that delimit blocks in SimaPro CSV
INPUT_SECTIONS = frozenset(
    {
        "Materials/fuels",
        "Electricity/heat",
        "Resources",
    }
)

OUTPUT_SECTIONS = frozenset(
    {
        "Products",
        "Emissions to air",
        "Emissions to water",
        "Emissions to soil",
        "Waste to treatment",
        "Final waste flows",
    }
)

ALL_SECTIONS = INPUT_SECTIONS | OUTPUT_SECTIONS

# Header line that marks beginning of a process block
PROCESS_START = "Process"
END_MARKER = "End"


class SimaProCSVSource(DataSource):
    """Data source for SimaPro CSV exports.

    SimaPro CSV uses a block-based format where sections are delimited by
    marker lines. This parser handles both v8.x and v9.x format variations.

    Args:
        path: Path to the SimaPro CSV file.
        encoding: File encoding. Defaults to "utf-8".
    """

    def __init__(self, path: str | Path, encoding: str = "utf-8"):
        self._path = Path(path)
        self._encoding = encoding

    @property
    def source_type(self) -> str:
        return "simapro_csv"

    @property
    def source_id(self) -> str:
        path_hash = hashlib.md5(str(self._path.resolve()).encode()).hexdigest()[:8]
        return f"simapro_{path_hash}"

    def get_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "path": str(self._path),
            "encoding": self._encoding,
            "format": "simapro_csv",
        }
        if self._path.exists():
            meta["size_bytes"] = self._path.stat().st_size
            try:
                lines = self._read_lines()
                meta["format_version"] = self._detect_format_version(lines)
            except Exception:
                pass
        return meta

    def validate(self) -> bool:
        """Validate that the file exists and looks like a SimaPro CSV."""
        if not self._path.exists():
            logger.warning("File not found: %s", self._path)
            return False

        try:
            lines = self._read_lines()
            if len(lines) < 3:
                logger.warning("File too short to be SimaPro CSV: %s", self._path)
                return False

            # Check for at least one recognized section marker
            found_section = False
            for line in lines:
                stripped = line.strip().rstrip(";")
                if stripped in ALL_SECTIONS or stripped == PROCESS_START:
                    found_section = True
                    break

            if not found_section:
                logger.warning("No SimaPro section markers found in: %s", self._path)
                return False

            return True
        except Exception as e:
            logger.warning("Failed to validate %s: %s", self._path, e)
            return False

    def extract(self) -> RawData:
        """Extract and structure LCI data from SimaPro CSV.

        Returns:
            RawData with content as dict:
                {
                    "processes": {
                        "Process Name": {
                            "inputs": [{"flow": ..., "amount": ..., "unit": ..., "section": ...}],
                            "outputs": [...]
                        }
                    },
                    "summary": {"total_flows": N, "processes": [...], "sections_found": [...]}
                }
        """
        if not self.validate():
            raise ValueError(f"Invalid SimaPro CSV file: {self._path}")

        lines = self._read_lines()
        version = self._detect_format_version(lines)
        processes = self._parse_blocks(lines)

        all_sections: set[str] = set()
        total_flows = 0
        for proc_data in processes.values():
            for flow in proc_data["inputs"] + proc_data["outputs"]:
                all_sections.add(flow.get("section", "unknown"))
                total_flows += 1

        content = {
            "processes": processes,
            "summary": {
                "total_flows": total_flows,
                "processes": sorted(processes.keys()),
                "sections_found": sorted(all_sections),
                "format_version": version,
            },
        }

        metadata = {
            "total_flows": total_flows,
            "process_count": len(processes),
            "sections_found": sorted(all_sections),
            "format_version": version,
            "path": str(self._path),
        }

        return RawData(
            content=content,
            content_type="structured",
            metadata=metadata,
            source=self,
        )

    def _read_lines(self) -> list[str]:
        """Read all lines from the CSV file."""
        with open(self._path, encoding=self._encoding) as f:
            return f.readlines()

    def _detect_format_version(self, lines: list[str]) -> str:
        """Detect SimaPro format version from header lines.

        Args:
            lines: All lines from the file.

        Returns:
            Version string like "9.x" or "8.x", or "unknown".
        """
        for line in lines[:20]:
            stripped = line.strip()
            # SimaPro header often contains version info
            if "SimaPro" in stripped:
                match = re.search(r"(\d+)\.(\d+)", stripped)
                if match:
                    major = match.group(1)
                    return f"{major}.x"
        return "unknown"

    def _parse_blocks(self, lines: list[str]) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Parse SimaPro CSV into process blocks.

        SimaPro CSV structure:
            Process
            ...header fields...
            <blank line>
            Products
            name;unit;amount;...
            <blank line>
            Materials/fuels
            name;unit;amount;...
            <blank line>
            ...more sections...
            End

        Args:
            lines: All lines from the file.

        Returns:
            Dict of process name -> {"inputs": [...], "outputs": [...]}.
        """
        processes: dict[str, dict[str, list[dict[str, Any]]]] = {}
        current_process: str | None = None
        current_section: str | None = None
        process_counter = 0

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Remove trailing semicolons (SimaPro uses ; as separator)
            clean = line.rstrip(";").strip()

            # Detect process start
            if clean == PROCESS_START:
                process_counter += 1
                # Try to find process name from subsequent lines
                current_process = self._extract_process_name(lines, i + 1, process_counter)
                if current_process not in processes:
                    processes[current_process] = {"inputs": [], "outputs": []}
                current_section = None
                i += 1
                continue

            # Detect end of process
            if clean == END_MARKER:
                current_process = None
                current_section = None
                i += 1
                continue

            # Detect section markers
            if clean in ALL_SECTIONS:
                current_section = clean
                i += 1
                continue

            # Parse data rows within a section
            if current_process and current_section and line and clean:
                flow = self._parse_flow_line(line, current_section)
                if flow:
                    if current_section in INPUT_SECTIONS:
                        processes[current_process]["inputs"].append(flow)
                    elif current_section in OUTPUT_SECTIONS:
                        processes[current_process]["outputs"].append(flow)

            i += 1

        return processes

    def _extract_process_name(self, lines: list[str], start_idx: int, counter: int) -> str:
        """Extract process name from lines following the Process marker.

        Looks for a non-empty, non-section-marker line as the process name.
        Falls back to "Process_N" if nothing found.
        """
        for j in range(start_idx, min(start_idx + 10, len(lines))):
            candidate = lines[j].strip().rstrip(";").strip()
            if not candidate:
                continue
            if candidate in ALL_SECTIONS or candidate == END_MARKER:
                break
            # Skip known header fields (key;value patterns with specific keys)
            if candidate.startswith(("Category type", "Type", "Comment", "Date")):
                continue
            return candidate

        return f"Process_{counter}"

    def _parse_flow_line(self, line: str, section: str) -> dict[str, Any] | None:
        """Parse a single flow data line.

        SimaPro uses semicolons as delimiters. Typical format:
            flow_name;unit;amount;[uncertainty_type;uncertainty_params;comment]

        Args:
            line: Raw CSV line.
            section: Current section name.

        Returns:
            Flow dict or None if the line is not parseable as data.
        """
        parts = [p.strip() for p in line.split(";")]

        # Need at least name, unit, amount
        if len(parts) < 3:
            return None

        flow_name = parts[0]
        if not flow_name:
            return None

        # Skip header-like rows
        if flow_name.lower() in ("name", "substance", "flow"):
            return None

        unit = parts[1] if len(parts) > 1 else ""

        # Parse amount (handle commas as decimal separator)
        amount_str = parts[2] if len(parts) > 2 else "0"
        try:
            amount = float(amount_str.replace(",", "."))
        except ValueError:
            return None

        flow: dict[str, Any] = {
            "flow": flow_name,
            "amount": amount,
            "unit": unit,
            "section": section,
        }

        # Optional: comment field (usually last non-empty part)
        if len(parts) > 3:
            comment_parts = [p for p in parts[3:] if p]
            if comment_parts:
                flow["comment"] = comment_parts[-1]

        return flow
