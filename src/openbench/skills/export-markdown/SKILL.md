# export-markdown

Write text content to a downloadable Markdown (.md) file and return a
file render item that the ChatEngine surfaces as an `ObFileCard`. The
lightweight sibling of `pdf-tools` (PDF deliverables) and
`export-excel` (spreadsheet deliverables) — use it when the user wants
plain-text/markdown output as a file rather than in the chat.

## Triggers

- User asks for a "markdown file", ".md file", "text file" deliverable
- User wants notes, documentation, or a summary saved as a file
- Agent composed long-form markdown the user needs offline

## Tools

- generate_markdown: write text content to a .md file

## Version

0.1.0
