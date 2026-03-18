"""Standard LCI Schema — categories, normalization, and validation.

Defines the universal output format that all data sources (EasyLCA, SimaPro,
Excel LDI) produce. Downstream agents (IO Table, Hotspot, Narrative) work
with this schema regardless of the input format.

Categories are bilingual (Indonesian/English) aligned with ISO 14040 and
PROPER 2025 standard. The 21 LDI categories map to 25 IO Table sections.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Standard Categories (bilingual: Indonesian <-> English)
# Each key is the IO Table section name (Indonesian).
# ---------------------------------------------------------------------------

STANDARD_CATEGORIES: dict[str, dict[str, Any]] = {
    "Bahan Baku": {
        "direction": "input",
        "ldi_number": 1,
        "english": "Raw Materials from Nature",
        "aliases": [
            "raw material from nature",
            "bahan baku dari alam",
            "bahan baku",
        ],
        "default_unit": None,
    },
    "Air": {
        "direction": "input",
        "ldi_number": 3,
        "english": "Water",
        "aliases": ["water", "air"],
        "default_unit": "L",
        "unit_conversions": {"barrel": 158.987, "m3": 1000},
    },
    "Bahan Pendukung Cairan": {
        "direction": "input",
        "ldi_number": 4,
        "english": "Liquid Supporting Material",
        "aliases": [
            "liquid supporting material",
            "bahan pendukung cairan",
            "b.p. cairan",
            "b.p.cairan",
        ],
        "default_unit": "L",
    },
    "Bahan Pendukung Padatan": {
        "direction": "input",
        "ldi_number": 5,
        "english": "Solid Supporting Material",
        "aliases": [
            "solid supporting material",
            "bahan pendukung padatan",
            "b.p. padatan",
            "b.p.padatan",
        ],
        "default_unit": "kg",
        "unit_conversions": {"ton": 1000},
    },
    "Transportasi Bahan Bakar dan Bahan Pendukung": {
        "direction": "input",
        "ldi_number": 6,
        "english": "Transport of Supporting Material",
        "aliases": [
            "transport of supporting material",
            "transportasi bahan bakar dan bahan pendukung",
            "transportasi",
        ],
        "default_unit": "km",
    },
    "Fuel Gas": {
        "direction": "input",
        "ldi_number": 7,
        "english": "Fuel Gas",
        "aliases": ["fuel gas", "bahan bakar gas"],
        "default_unit": "MMSCF",
    },
    "Bahan Bakar Cair": {
        "direction": "input",
        "ldi_number": 8,
        "english": "Liquid Fuels",
        "aliases": [
            "liquid fuels",
            "bahan bakar cair",
            "b.b. cair",
            "b.b.cair",
        ],
        "default_unit": "L",
    },
    "Listrik": {
        "direction": "input",
        "ldi_number": 9,
        "english": "Electricity",
        "aliases": ["electricity", "listrik"],
        "default_unit": "kWh",
    },
    "Infrastruktur": {
        "direction": "input",
        "ldi_number": 10,
        "english": "Infrastructure",
        "aliases": ["infrastructure", "infrastruktur"],
        "default_unit": "kg",
        "unit_conversions": {"ton": 1000},
        "special_rules": ["annualize_by_lifetime"],
    },
    "Lahan Digunakan": {
        "direction": "input",
        "ldi_number": 12,
        "english": "Land Used",
        "aliases": ["land used", "lahan digunakan", "land"],
        "default_unit": "m2a",
        "unit_conversions": {"m2": "multiply_by_study_over_lifetime"},
    },
    "Lahan Ditransformasi": {
        "direction": "input",
        "ldi_number": 12,
        "english": "Land Transformed",
        "aliases": ["land transformed", "lahan ditransformasi"],
        "default_unit": "m2",
    },
    "Produk": {
        "direction": "output",
        "ldi_number": 14,
        "english": "Product",
        "aliases": ["product", "produk"],
        "default_unit": None,
    },
    "Sampah": {
        "direction": "output",
        "ldi_number": 16,
        "english": "Non-Hazardous Waste",
        "aliases": [
            "non-hazardous waste",
            "limbah non-b3",
            "limbah non b3",
            "sampah",
        ],
        "default_unit": "kg",
        "unit_conversions": {"ton": 1000},
    },
    "Limbah B3": {
        "direction": "output",
        "ldi_number": 17,
        "english": "Hazardous Waste",
        "aliases": ["hazardous waste", "limbah b3"],
        "default_unit": "kg",
        "unit_conversions": {"ton": 1000},
    },
    "Limbah Cair": {
        "direction": "output",
        "ldi_number": 18,
        "english": "Liquid Waste",
        "aliases": ["liquid waste", "limbah cair"],
        "default_unit": "L",
    },
    "Kandungan Limbah Cair": {
        "direction": "output",
        "ldi_number": 19,
        "english": "Liquid Waste Substances",
        "aliases": [
            "liquid waste substances",
            "kandungan limbah cair",
            "kand. limbah cair",
        ],
        "default_unit": "kg",
    },
    "Emisi Udara": {
        "direction": "output",
        "ldi_number": 20,
        "english": "Air Emissions",
        "aliases": ["air emissions", "emisi udara"],
        "default_unit": "kg",
        "unit_conversions": {"ton": 1000},
        "emission_details": [
            "CO2",
            "CH4",
            "CO",
            "NOx",
            "N2O",
            "SOx",
            "Particulate Material",
            "nmVOC",
            "TOC",
        ],
    },
}

# ---------------------------------------------------------------------------
# Reverse alias lookup: alias (lowercase) -> standard category key
# ---------------------------------------------------------------------------

_ALIAS_MAP: dict[str, str] = {}
for _key, _info in STANDARD_CATEGORIES.items():
    _ALIAS_MAP[_key.lower()] = _key
    for _alias in _info.get("aliases", []):
        _ALIAS_MAP[_alias.lower()] = _key

# ---------------------------------------------------------------------------
# Category sets
# ---------------------------------------------------------------------------

INPUT_CATEGORIES: frozenset[str] = frozenset(
    k for k, v in STANDARD_CATEGORIES.items() if v["direction"] == "input"
)

OUTPUT_CATEGORIES: frozenset[str] = frozenset(
    k for k, v in STANDARD_CATEGORIES.items() if v["direction"] == "output"
)

# LDI categories excluded from IO Table (not part of final output)
EXCLUDED_LDI_CATEGORIES: frozenset[str] = frozenset(
    {
        "Raw Material from Processes",  # LDI #2
        "Other Supporting Material",  # LDI #21
    }
)

# LDI categories used only as helper data (lifetime values)
HELPER_LDI_CATEGORIES: frozenset[str] = frozenset(
    {
        "Projected Lifetime of Infrastructure",  # LDI #11
        "Projected Lifetime of Land",  # LDI #13
    }
)

# ---------------------------------------------------------------------------
# IO Table section order (25 sections, from PROPER format screenshot)
# ---------------------------------------------------------------------------

IO_TABLE_SECTION_ORDER: list[str] = [
    # INPUTS (11 sections)
    "Bahan Baku",
    "Air",
    "Bahan Pendukung Cairan",
    "Bahan Pendukung Padatan",
    "Transportasi Bahan Bakar dan Bahan Pendukung",
    "Fuel Gas",
    "Bahan Bakar Cair",
    "Listrik",
    "Infrastruktur",
    "Lahan Digunakan",
    "Lahan Ditransformasi",
    # OUTPUTS (14 sections)
    "Produk",
    "Sampah",
    "Limbah B3",
    "Limbah Cair",
    "Kandungan Limbah Cair",
    "Emisi Udara",
    "Emisi CO2",
    "Emisi CH4",
    "Emisi CO",
    "Emisi NOx",
    "Emisi N2O",
    "Emisi SOx",
    "Emisi Particulate Material",
    "Emisi nmVOC",
    "Emisi TOC",
]

# Emission detail sections (derived from Emisi Udara breakdown)
EMISSION_DETAIL_SECTIONS: list[str] = [
    "Emisi CO2",
    "Emisi CH4",
    "Emisi CO",
    "Emisi NOx",
    "Emisi N2O",
    "Emisi SOx",
    "Emisi Particulate Material",
    "Emisi nmVOC",
    "Emisi TOC",
]


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def normalize_category(name: str) -> str | None:
    """Map a category name (any language/alias) to standard IO Table key.

    Returns None if the name is not recognized.
    """
    if not name:
        return None
    return _ALIAS_MAP.get(name.strip().lower())


def category_direction(standard_key: str) -> str | None:
    """Return 'input' or 'output' for a standard category key."""
    info = STANDARD_CATEGORIES.get(standard_key)
    return info["direction"] if info else None


def is_excluded_ldi(category_name: str) -> bool:
    """Check if an LDI category should be excluded from IO Table."""
    return category_name.strip() in EXCLUDED_LDI_CATEGORIES


def is_helper_ldi(category_name: str) -> bool:
    """Check if an LDI category is a helper (lifetime values)."""
    return category_name.strip() in HELPER_LDI_CATEGORIES


# ---------------------------------------------------------------------------
# Unit normalization
# ---------------------------------------------------------------------------

UNIT_ALIASES: dict[str, str] = {
    "kilogram": "kg",
    "kilograms": "kg",
    "kilo": "kg",
    "ton": "ton",
    "tonne": "ton",
    "tonnes": "ton",
    "metric ton": "ton",
    "liter": "L",
    "litre": "L",
    "liters": "L",
    "litres": "L",
    "l": "L",
    "barrel": "barrel",
    "barrels": "barrel",
    "bbl": "barrel",
    "cubic meter": "m3",
    "cubic metre": "m3",
    "m³": "m3",
    "kwh": "kWh",
    "kilowatt-hour": "kWh",
    "kilowatt hour": "kWh",
    "kilometer": "km",
    "kilometres": "km",
    "kilometers": "km",
    "square meter": "m2",
    "square metre": "m2",
    "m²": "m2",
    "m2a": "m2a",
    "m²a": "m2a",
    "m2.a": "m2a",
    "mmscf": "MMSCF",
}


def normalize_unit(unit: str) -> str:
    """Normalize a unit string to its canonical form."""
    if not unit:
        return unit
    cleaned = unit.strip()
    return UNIT_ALIASES.get(cleaned.lower(), cleaned)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def validate_lci_schema(data: dict[str, Any]) -> list[str]:
    """Validate that data conforms to the standard LCI schema.

    Expected structure:
        {
            "flows": [
                {
                    "category": str,     # standard category key
                    "flow_name": str,
                    "amount": float,
                    "unit": str,
                    "direction": "input" | "output",
                    "process": str,      # optional
                }
            ],
            "products": [...],           # optional
        }

    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Data must be a dictionary"]

    flows = data.get("flows")
    if not isinstance(flows, list):
        return ["Data must contain a 'flows' list"]

    for i, flow in enumerate(flows):
        if not isinstance(flow, dict):
            errors.append(f"Flow [{i}]: must be a dictionary")
            continue

        # Required fields
        for field in ("category", "flow_name", "amount", "unit", "direction"):
            if field not in flow:
                errors.append(f"Flow [{i}]: missing required field '{field}'")

        # Category validation
        cat = flow.get("category", "")
        if cat and cat not in STANDARD_CATEGORIES and cat not in EMISSION_DETAIL_SECTIONS:
            errors.append(f"Flow [{i}]: unknown category '{cat}'")

        # Direction validation
        direction = flow.get("direction", "")
        if direction and direction not in ("input", "output"):
            errors.append(f"Flow [{i}]: direction must be 'input' or 'output', got '{direction}'")

        # Amount validation
        amount = flow.get("amount")
        if amount is not None and not isinstance(amount, (int, float)):
            errors.append(f"Flow [{i}]: amount must be numeric, got {type(amount).__name__}")

    return errors
