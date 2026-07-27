# export-excel

Write records to an Excel workbook and return a file render item that
the ChatEngine surfaces as an `ObFileCard`. Supports both single-sheet
and multi-sheet exports. Use it whenever the user wants a downloadable
spreadsheet rather than an in-chat table.

The skill does not attempt to style cells, freeze panes, or auto-fit
columns. It writes clean, predictable data that downstream tools
(pandas, Power Query, Looker) can re-read without surprises.

## Triggers

Trigger on these regardless of the language the user writes in.

- English: "export", "download", "save to Excel", "send me as xlsx",
  "spreadsheet", "workbook"
- Bahasa Indonesia: "ekspor", "unduh", "buatkan file excel", "simpan
  sebagai xlsx", "berkas excel", "lembar kerja"
- Agent has a final computed dataset that the user needs for offline work
- User wants a multi-sheet report (one sheet per category, per year, etc.)
- A previous skill produced records that the user wants to share with
  someone who can't see the chat

When the user asks for a file, answering with a markdown table alone is
not enough — call the tool and return the download card. For PDF use
`generate_pdf`; for markdown/text use `generate_markdown`.

## Tools

- export_to_excel: write a single list of records to one sheet
- export_multi_sheet_excel: write multiple named sheets in one workbook

## Dependencies

- pandas >= 2.0.0
- openpyxl >= 3.1.0

## Version

0.1.0
