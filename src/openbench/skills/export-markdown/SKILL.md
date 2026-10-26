# export-markdown

Write text content to a downloadable Markdown (.md) file and return a
file render item that the ChatEngine surfaces as an `ObFileCard`. The
lightweight sibling of `pdf-tools` (PDF deliverables) and
`export-excel` (spreadsheet deliverables) — use it when the user wants
plain-text/markdown output as a file rather than in the chat.

## Triggers

Trigger on these regardless of the language the user writes in.

- User asks for a "markdown file", ".md file", "text file" deliverable
  (Indonesian: "simpan sebagai markdown", "unduh file md", "berkas teks")
- User wants notes, documentation, or a summary saved as a file
  (Indonesian: "buatkan catatan dalam berkas", "ekspor catatan")
- Agent composed long-form markdown the user needs offline

When the user asks for a file, answering in the chat alone is not enough
— call `generate_markdown` and return the download card. For PDF use
`generate_pdf`; for spreadsheets use `export_to_excel`.

## Tools

- generate_markdown: write text content to a .md file

## Version

0.1.0
