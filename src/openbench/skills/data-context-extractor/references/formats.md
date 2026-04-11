# File Format Reference

Default behaviors and known edge cases for every format this skill can read.

## CSV / TSV

- Default encoding: `utf-8-sig` (handles Microsoft BOM prefix automatically)
- Separator auto-detection:
  - `.csv` → comma
  - `.tsv` → tab
  - Override with the `separator` argument
- Row limit default: 1000 rows (use `limit=None` for full file)
- Columns with mixed types are returned as `object`; agents should
  coerce before aggregating

## Excel (.xlsx, .xls)

- Reader: `openpyxl` for `.xlsx`, `xlrd` legacy fallback for `.xls`
- Multi-sheet workbooks: call `list_excel_sheets` first, then
  `read_excel_file(sheet=...)` per sheet
- Header row is the first non-empty row unless `header_row` is set
- Merged cells are flattened by forward-filling the top-left value

## JSON

- Top-level list of objects → treated as records
- Top-level object with a `data`/`records`/`rows` list → records extracted
- Top-level object with scalar fields → returned as a single record
- Deeply nested JSON is not flattened; agents should normalize first

## Schema Summary Shape

Every reader returns the same dict shape so downstream skills can
consume them uniformly::

    {
        "source": "<absolute path>",
        "format": "csv" | "tsv" | "xlsx" | "xls" | "json",
        "row_count": int,
        "columns": [
            {"name": "...", "dtype": "int64" | "float64" | "object" | ...}
        ],
        "sample": [ {...row_dict...}, ... ],   # up to 5 rows
        "records": [ {...row_dict...}, ... ],  # full data, may be omitted
    }

## Error Contract

On failure the tool returns `{"error": "...", "source": "<path>"}` rather
than raising. This lets the agent recover gracefully in a reasoning loop.
