# data-context-extractor

Read any tabular or semi-structured file (CSV, Excel, JSON, TSV) and return
a normalized summary the agent can reason over: column names, inferred
dtypes, row count, and a small sample of rows. Use this as the very first
step whenever the user uploads a file or asks about the contents of a
path — it gives the agent cheap, structured ground truth about what's in
the file without reading the whole thing into the prompt.

This is an SDK-level skill: every OpenBench project gets it for free, so
downstream skills (query-explorer, data-visualization, export-excel, and
project-specific parsers) can rely on a consistent `{file, schema,
sample}` contract.

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

## Tools

- extract_file_context: auto-detect the format and return a schema summary
- read_csv_file: read a CSV/TSV and return records + metadata
- read_excel_file: read a single Excel sheet and return records + metadata
- list_excel_sheets: list every sheet name in an Excel workbook

## Dependencies

- pandas >= 2.0.0
- openpyxl >= 3.1.0

## Version

0.1.0
