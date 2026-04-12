# xql

Treat Excel sheets as relational tables. XQL (Excel Query Language) gives
Lici SQL-like primitives — SELECT / WHERE / PROJECT / GROUP BY / JOIN /
UNION / PIVOT / PARETO — that operate over messy LCI workbooks without
the user writing Python or SQL.

This skill exists to solve a real problem in LCI work: data lives across
multiple Excel files with inconsistent schemas (renamed columns, multi-row
headers, mixed units), and analysts resort to copy-paste, VLOOKUP chains,
or one-off Python scripts. XQL treats each sheet as a named table with a
canonical alias-based schema, so queries are portable across files.

## Triggers

- User uploads or points at an .xlsx workbook
- User asks about specific columns, categories, or flows in a sheet
- User asks for totals, averages, rankings, or Pareto breakdowns
- User wants to join or compare data across two sheets or two files
- User wants to build an IO table or a pivoted summary
- User mentions "LCI", "LDI", "inventory", "raw materials", "emissions",
  "aggregate by", "top N", "group by", "compare", "merge"

## Dependencies

- pandas (already a lci-mini dependency)
- openpyxl (Excel reader)
- pyyaml (load config/*.yaml at skill initialization)

## Version

0.1.0

## Architecture

Three layers, all implemented in ``tools.py``:

- **Layer 0 — CATALOG**: ``xql_catalog``, ``xql_list_tables``,
  ``xql_describe_table``. Discovers every sheet as a named table with a
  normalized schema. Handles multi-row headers, unnamed columns, and
  schema drift via a column alias registry.
- **Layer 1 — QUERY**: ``xql_select``, ``xql_project``, ``xql_where``,
  ``xql_order``, ``xql_group``, ``xql_distinct``, ``xql_pareto``.
  Single-table relational operators. Alias-first column resolution.
- **Layer 2 — TRANSFORM**: ``xql_join``, ``xql_union``, ``xql_pivot``,
  ``xql_build_io_table``. Multi-table operators and LCI-specific helpers.

Configuration lives in ``config/``:

- ``aliases.yaml``   — logical column name -> list of physical names
  (UNIVERSAL names only — no site-specific columns)
- ``units.yaml``     — unit conversion factors (mass, volume, energy)
- ``lci_rules.yaml`` — Pareto thresholds, grouping rules, exclusions

## Column Resolution Strategy

XQL uses a TWO-TIER column resolution:

1. **Alias config** (config/aliases.yaml) — maps universal logical
   names (category, material, unit, io) to common physical names.
   Works for standard columns present in every LCI file.

2. **LLM inference + Column Profile** (data-context-extractor SDK skill)
   — for site-specific columns (amount, functional unit, custom metrics).
   The agent reads xql_describe_table output, identifies the correct
   column by name + dtype, then persists the mapping via
   save_column_profile. Next session: profile loaded from disk, zero
   re-mapping cost.

Site-specific columns like "Semberah EP", "Cirebon Plant", or
"FU - Clinker" do NOT belong in aliases.yaml. They are mapped
dynamically by the LLM and cached by the column profile system.

All queries return results inline (JSON-serializable list of row dicts)
unless the caller asks to persist them. Source .xlsx files are **never**
modified.

## Natural Language Mapping

| User says | Primitives |
|---|---|
| "Tampilkan bahan pendukung cair" | ``xql_where(category="Liquid Supporting Material")`` |
| "Total listrik per proses" | ``xql_where(category="Electricity")`` → ``xql_group(process, {amount: sum})`` |
| "Bandingkan Semberah EP vs Tanjung" | ``xql_join(file1.sheet, file2.sheet, on=[process, category, material])`` |
| "Top 80% emisi CO2" | ``xql_pareto(filter={material: "CO2"}, threshold=0.80)`` |
| "Buat IO Table" | ``xql_build_io_table(source, products, rules)`` |
| "Berapa jenis material di tiap kategori?" | ``xql_group(category, {material: nunique})`` |
| "Gabungkan data kedua file" | ``xql_union([left_table, right_table])`` |
| "Distinct kategori yang ada?" | ``xql_distinct(columns=[category])`` |

## Execution Flow (example)

User: *"berapa total diesel yang dipakai per proses?"*

1. ``xql_catalog(files=["input.xlsx"])`` — register every sheet
2. ``xql_list_tables()`` — find a sheet that mentions Liquid Fuels
3. ``xql_where(table_id=..., conditions=[(category, "==", "Liquid Fuels"), (material, "LIKE", "Diesel")])``
4. ``xql_group(group_by=["process"], agg={"amount": "sum"})``
5. ``xql_order(by="amount_sum", ascending=False)``
6. Display as a table

## Hard Boundaries

- Never mutate source .xlsx files — output always goes to new tables
- Never fabricate data — if a join has zero matches, surface it clearly
- Always normalize units before aggregating across rows
- Warn (don't error) on mixed-unit sums; show conversion factor used
