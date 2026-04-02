"""MappingProfile system — load, save, and match column-mapping profiles.

A MappingProfile captures how a specific company's LDI Master Excel maps
to the Standard LCI Schema. Profiles are saved as JSON and reused so the
LLM only needs to generate the mapping once per company format.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directory containing saved profile JSON files
PROFILES_DIR = Path(__file__).parent


def _normalize_column_mapping(profile: dict[str, Any]) -> dict[str, Any]:
    """Normalize column_mapping values from int to {"index": int}.

    LLM-generated profiles may use shorthand ``{"process": 0}`` instead of
    the canonical ``{"process": {"index": 0, "header": "Process Title"}}``.
    This function converts the shorthand form so downstream code that calls
    ``col_spec.get("index")`` does not crash.
    """
    col_map = profile.get("column_mapping")
    if not isinstance(col_map, dict):
        return profile

    normalized: dict[str, Any] = {}
    changed = False
    for key, spec in col_map.items():
        if isinstance(spec, int):
            normalized[key] = {"index": spec}
            changed = True
        elif not isinstance(spec, dict):
            try:
                normalized[key] = {"index": int(spec)}
                changed = True
            except (ValueError, TypeError):
                normalized[key] = spec
        else:
            normalized[key] = spec

    if changed:
        profile["column_mapping"] = normalized
    return profile


def list_profiles() -> list[dict[str, Any]]:
    """List all saved profiles with their metadata.

    Returns:
        List of dicts with keys: profile_name, file_name, company, scope.
    """
    profiles = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profiles.append(
                {
                    "profile_name": data.get("profile_name", path.stem),
                    "file_name": path.name,
                    "company": data.get("company", ""),
                    "scope": data.get("scope", ""),
                }
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read profile %s: %s", path, exc)
    return profiles


def load_profile(name: str) -> dict[str, Any]:
    """Load a saved MappingProfile by name.

    Args:
        name: Profile name (stem of the JSON file, e.g. 'pertamina_pep_tanjung').

    Returns:
        The full MappingProfile dict.

    Raises:
        FileNotFoundError: If the profile does not exist.
    """
    path = PROFILES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {name} (looked at {path})")
    profile = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_column_mapping(profile)


def save_profile(name: str, profile: dict[str, Any]) -> Path:
    """Save a MappingProfile to disk.

    Args:
        name: Profile name (will be saved as <name>.json).
        profile: The MappingProfile dict.

    Returns:
        Path to the saved file.
    """
    path = PROFILES_DIR / f"{name}.json"
    path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Saved profile to %s", path)
    return path


def match_profile(excel_profile: dict[str, Any]) -> dict[str, Any] | None:
    """Find a saved MappingProfile that matches the given Excel structure.

    Matching heuristic (ordered by specificity):
    1. Exact sheet name match
    2. Header pattern similarity (>80% overlap) + column position verification

    Args:
        excel_profile: Output from ExcelProfile.extract() — must contain
            'sheets' dict with sheet profiles.

    Returns:
        The matching MappingProfile dict, or None if no match found.
    """
    sheet_names = set(excel_profile.get("sheet_names", []))

    for path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        # Strategy 1: Check if profile's target sheet name exists
        target_sheet = profile.get("sheet_name", "")
        if target_sheet and target_sheet in sheet_names:
            logger.info("Profile matched by sheet name: %s -> %s", target_sheet, path.stem)
            return _normalize_column_mapping(profile)

        # Strategy 2: Header overlap with profile's expected columns
        expected_headers = set(profile.get("expected_headers", []))
        if not expected_headers:
            continue

        for sheet_info in excel_profile.get("sheets", {}).values():
            actual_headers = {h.lower() for h in sheet_info.get("headers", []) if h is not None}
            expected_lower = {h.lower() for h in expected_headers}
            if not expected_lower:
                continue
            overlap = len(actual_headers & expected_lower) / len(expected_lower)
            if overlap <= 0.8:
                continue

            # Verify column positions: headers at mapped indexes must match
            col_map = profile.get("column_mapping", {})
            if col_map and not _verify_column_positions(sheet_info.get("headers", []), col_map):
                logger.debug(
                    "Profile %s rejected: header overlap %.0f%% but column positions mismatch",
                    path.stem,
                    overlap * 100,
                )
                continue

            logger.info(
                "Profile matched by headers (%.0f%% overlap): %s",
                overlap * 100,
                path.stem,
            )
            return _normalize_column_mapping(profile)

    return None


def _verify_column_positions(
    actual_headers: list[str | None],
    column_mapping: dict[str, dict[str, Any]],
) -> bool:
    """Check that headers at mapped column indexes match expected header names.

    Returns True if >80% of column positions match (allowing minor drift).
    """
    checks = 0
    matches = 0

    for field_spec in column_mapping.values():
        # Handle both {"index": N, "header": "..."} and shorthand int format
        if isinstance(field_spec, int):
            continue  # No header to verify, skip
        if not isinstance(field_spec, dict):
            continue
        idx = field_spec.get("index")
        expected_header = field_spec.get("header")
        if idx is None or expected_header is None:
            continue

        checks += 1
        if idx < len(actual_headers) and actual_headers[idx] is not None:
            if actual_headers[idx].lower().strip() == expected_header.lower().strip():
                matches += 1

    if checks == 0:
        return True

    ratio = matches / checks
    logger.debug("Column position verification: %d/%d (%.0f%%)", matches, checks, ratio * 100)
    return ratio > 0.8
