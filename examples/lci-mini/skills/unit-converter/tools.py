"""Unit conversion tool for common LCA units.

Exports:
    convert_unit(value, from_unit, to_unit) -> {"value": float, "unit": str}
"""

from __future__ import annotations

# Internal conversion to a canonical base unit per dimension.
# Factor = how many base units in 1 source unit.
_MASS_BASE = "kg"
_MASS_FACTORS = {
    "kg": 1.0,
    "g": 0.001,
    "ton": 1000.0,
    "tonne": 1000.0,
    "t": 1000.0,
}

# Volume covers both liquid and gas-at-standard-conditions.
# All factors convert TO liters (the base unit for this dimension).
_VOLUME_BASE = "L"
_VOLUME_FACTORS = {
    "L": 1.0,
    "liter": 1.0,
    "litre": 1.0,
    "m3": 1000.0,
    "barrel": 158.987,  # US petroleum barrel
    "bbl": 158.987,
    "gallon": 3.78541,  # US gallon
    # Gas volumes at standard conditions (petroleum industry):
    # 1 SCF = 0.028316847 m3 = 28.316847 L
    # 1 MMSCF = 1,000,000 SCF = 28,316,847 L
    "SCF": 28.316847,
    "MMSCF": 28_316_847.0,
}

_ENERGY_BASE = "MJ"
_ENERGY_FACTORS = {
    "MJ": 1.0,
    "kWh": 3.6,
    "GJ": 1000.0,
    "kcal": 0.004184,
}

_DIMENSIONS: dict[str, dict[str, float]] = {
    "mass": _MASS_FACTORS,
    "volume": _VOLUME_FACTORS,
    "energy": _ENERGY_FACTORS,
}


def _find_dimension(unit: str) -> str | None:
    """Return the dimension name that contains this unit, or None."""
    for name, table in _DIMENSIONS.items():
        if unit in table:
            return name
    return None


def convert_unit(value: float, from_unit: str, to_unit: str) -> dict:
    """Convert a value between units within the same physical dimension.

    Args:
        value: Numeric amount to convert.
        from_unit: Source unit (e.g. "ton", "barrel", "MJ", "MMSCF").
        to_unit: Target unit in the same dimension (e.g. "kg", "L", "kWh").

    Returns:
        Dict with keys ``value`` (converted float) and ``unit`` (target).

    Raises:
        ValueError: If either unit is unknown or they belong to different
            physical dimensions.
    """
    src_dim = _find_dimension(from_unit)
    dst_dim = _find_dimension(to_unit)

    if src_dim is None:
        raise ValueError(
            f"Unknown source unit: {from_unit!r}. "
            f"Supported: {sorted(k for t in _DIMENSIONS.values() for k in t)}"
        )
    if dst_dim is None:
        raise ValueError(
            f"Unknown target unit: {to_unit!r}. "
            f"Supported: {sorted(k for t in _DIMENSIONS.values() for k in t)}"
        )
    if src_dim != dst_dim:
        raise ValueError(
            f"Cannot convert {from_unit!r} ({src_dim}) to {to_unit!r} ({dst_dim}) "
            f"— different physical dimensions."
        )

    table = _DIMENSIONS[src_dim]
    base_value = value * table[from_unit]
    converted = base_value / table[to_unit]
    return {"value": converted, "unit": to_unit}


CONVERT_UNIT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "convert_unit",
        "description": (
            "Convert a numeric value between units in the same physical "
            "dimension (mass, volume, energy, or gas volume). Common LCA "
            "conversions: ton->kg, barrel->L, MJ->kWh, MMSCF->m3."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "number",
                    "description": "Numeric value to convert",
                },
                "from_unit": {
                    "type": "string",
                    "description": "Source unit (ton, barrel, MJ, MMSCF, etc.)",
                },
                "to_unit": {
                    "type": "string",
                    "description": "Target unit in the same physical dimension",
                },
            },
            "required": ["value", "from_unit", "to_unit"],
        },
    },
}
