# unit-converter

Unit conversions commonly needed in LCA work — mass, volume, energy,
and petroleum-industry units — with one tool, ``convert_unit``.

Lici uses this skill to answer questions like "berapa kg kalau 2 ton?",
"barrel ke liter gimana?", and to coach consultants on unit normalization
when they're preparing LDI data for aggregation.

## Triggers
- User asks for a unit conversion (ton→kg, barrel→L, MMSCF→m³, MJ→kWh)
- User mentions mismatched units in an IO table
- User asks why aggregation failed due to mixed units

## Dependencies
- None (self-contained tool skill)

## Version
0.1.0

## Supported Conversions

Mass: `ton` ↔ `kg`, `g`
Volume: `barrel` (US bbl) ↔ `L`, `m3`, `gallon`
Energy: `MJ` ↔ `kWh`, `GJ`, `kcal`
Gas: `MMSCF` (million standard cubic feet) → `m3`

All factors hard-coded from standard LCA reference values. For anything
outside this list, recommend ecoinvent or the user's own database.
