# xql

Treat Excel sheets as relational tables. XQL gives Lici SQL-like
primitives — SELECT / WHERE / PROJECT / GROUP BY / JOIN / UNION / PIVOT
/ PARETO — that operate over messy LCI workbooks without the user
writing Python or SQL.

## Triggers

- User attaches or references an `.xlsx` workbook.
- User asks about columns, categories, flows, totals, rankings, or
  Pareto breakdowns.
- User wants to join/compare data across sheets or files, or build an
  IO table.
- User mentions LCI, LDI, inventory, raw materials, emissions,
  "aggregate by", "top N", "group by", "compare", "merge".

## Version

0.1.0

## Column Resolution Protocol

When querying an attached file, follow this order:

1. `extract_file_context(path)` — check `profile_status`.
   - `cached` → use the returned `column_roles` directly, skip to
     querying.
   - `needs_mapping` → continue.
2. `xql_describe_table(table_id)` — get columns, dtypes, samples.
3. Map each column:
   - Standard columns (category / material / unit / io / process) use
     alias names; XQL resolves them via `config/aliases.yaml`.
   - Numeric columns without standard names (site/plant columns, FU
     columns, custom metrics):
     - Site/plant/location name → role `amount`.
     - Contains "FU", "Functional Unit", "Per" → role
       `functional_unit`.
     - Ambiguous or multiple candidates → **ask the user** which one
       they want analyzed.
4. `save_column_profile(path, mappings)` — persist inferred roles so
   the next session skips re-mapping.
5. Always use physical column names (from describe/profile) in xql_*
   calls. Alias names also work for standard columns.
6. Never hardcode column names from prior conversations; each file may
   have different headers. If the user corrects a mapping, call
   `update_column_profile(path, column, role)`.

## Natural Language Mapping

| User says | Primitives |
|---|---|
| "Tampilkan bahan pendukung cair" | `xql_where(category="Liquid Supporting Material")` |
| "Total listrik per proses" | `xql_where(category="Electricity")` → `xql_group(process, {amount: sum})` |
| "Bandingkan Semberah EP vs Tanjung" | `xql_join(file1.sheet, file2.sheet, on=[process, category, material])` |
| "Top 80% emisi CO2" | `xql_pareto(filter={material: "CO2"}, threshold=0.80)` |
| "Buat IO Table" | `xql_build_io_table(source, products, rules)` |
| "Berapa jenis material di tiap kategori?" | `xql_group(category, {material: nunique})` |
| "Gabungkan data kedua file" | `xql_union([left_table, right_table])` |
| "Distinct kategori yang ada?" | `xql_distinct(columns=[category])` |

## Typical Flow

`xql_catalog()` (no args — server injects paths) → `xql_list_tables()`
→ pick `table_id` → `xql_where` / `xql_group` / `xql_order` / `xql_pareto`.

## Hard Boundaries

- Never mutate source `.xlsx` files — results go to new tables.
- Never fabricate data — if a join has zero matches, surface it.
- Always normalize units before aggregating.
- Warn (don't error) on mixed-unit sums; show the conversion factor
  used.
