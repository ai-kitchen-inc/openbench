# export-excel

Write records to an Excel workbook and return a file render item that
the ChatEngine surfaces as an `ObFileCard`. Supports both single-sheet
and multi-sheet exports. This is the companion "finish step" to
`data-visualization` — use it when the user wants a downloadable
deliverable rather than an in-chat visual.

The skill does not attempt to style cells, freeze panes, or auto-fit
columns. It writes clean, predictable data that downstream tools
(pandas, Power Query, Looker) can re-read without surprises.

## Triggers

- User asks to "export", "download", "save to Excel", "send me as xlsx"
- Agent has a final computed dataset that the user needs for offline work
- User wants a multi-sheet report (one sheet per category, per year, etc.)
- A previous skill produced records that the user wants to share with
  someone who can't see the chat

## Tools

- export_to_excel: write a single list of records to one sheet
- export_multi_sheet_excel: write multiple named sheets in one workbook

## Dependencies

- pandas >= 2.0.0
- openpyxl >= 3.1.0

## Version

0.1.0
