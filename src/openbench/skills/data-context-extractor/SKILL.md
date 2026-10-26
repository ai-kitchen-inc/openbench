# data-context-extractor

Read any tabular or semi-structured file (CSV, Excel, JSON, TSV) and return
a normalized summary the agent can reason over: column names, inferred
dtypes, row count, and a small sample of rows. Use this as the very first
step whenever the user uploads a file or asks about the contents of a
path — it gives the agent cheap, structured ground truth about what's in
the file without reading the whole thing into the prompt.

Also provides a **column profile** system: once the agent infers column
roles (amount, category, metric, label, etc.), it saves a profile to disk
keyed by file content hash. Subsequent sessions with the same file skip
re-mapping entirely — the profile is loaded automatically.

This is an SDK-level skill: every OpenBench project gets it for free, so
downstream skills (query-explorer, data-visualization, export-excel, and
project-specific parsers) can rely on a consistent `{file, schema,
sample, column_roles}` contract.

## Triggers

- User uploads or mentions a `.csv`, `.tsv`, `.xlsx`, `.xls`, or `.json` file
- User asks "what's in this file?", "what columns does it have?", or
  similar schema-exploration questions
- Agent needs to plan a query or transformation but does not yet know
  the column names or data types
- Another skill (e.g. query-explorer) needs a schema handoff before
  operating on the file

## References

- formats.md: supported file formats, encoding defaults, and common
  edge cases (multi-sheet Excel, BOM-prefixed CSV, nested JSON)
- column-roles.md: standard column roles and how to infer them

## Tools

- extract_file_context: auto-detect format, return schema + profile status
- read_csv_file: read a CSV/TSV and return records + metadata
- read_excel_file: read a single Excel sheet and return records + metadata
- list_excel_sheets: list every sheet name in an Excel workbook
- save_column_profile: persist LLM-inferred column role mappings to disk
- get_column_profile: load cached profile for a file
- update_column_profile: correct a single column's role (user override)

## Column Resolution Protocol

1. Call extract_file_context — check profile_status in response
2. If profile_status == "cached": use column_roles directly, skip mapping
3. If profile_status == "needs_mapping":
   a. Identify unmapped columns by dtype + name
   b. Call save_column_profile with your mappings
   c. Proceed with queries using physical column names
4. If user corrects a mapping: call update_column_profile

## Dependencies

- pandas >= 2.0.0
- openpyxl >= 3.1.0

## Version

0.2.0
