# PDF Processing Guide

## When to Use Each Tool

| Situation | Tool | Why |
|---|---|---|
| First encounter with a PDF | `pdf_metadata` | Cheap — get page count before deciding |
| Need text content | `read_pdf` (small) or `read_pdf_page` (large) | Avoid context blow-up |
| Need structured data | `extract_pdf_tables` | Tables auto-detected by pdfplumber |
| Combine multiple files | `merge_pdfs` | Single output file |
| Extract specific pages | `split_pdf` | Subset of original |
| Create deliverable | `generate_pdf` | Structured report |

## Reading Strategy for Large PDFs

```
pdf_metadata → page_count = 85
  → DON'T: read_pdf (would be ~200K chars, blows context)
  → DO: read_pdf(pages=[0, 1, 2]) for introduction
  → DO: read_pdf_page(page=10) for specific section
  → DO: extract_pdf_tables(page=5) for data on page 5
```

## Table Extraction Tips

- pdfplumber works best on PDFs with **visible grid lines**
- Scanned PDFs (images) → tables will NOT be detected (need OCR, not available in v0.1)
- If no tables found but you can see them → the PDF may use invisible borders
- Tables are pushed to render queue → ObTable appears in chat automatically
- Convert table to records for further analysis with query-explorer tools

## Generate PDF — Section Types

```json
{"type": "heading", "content": "Section Title"}
{"type": "text", "content": "Paragraph of text..."}
{"type": "table", "headers": ["Col A", "Col B"], "rows": [["val1", "val2"]]}
```

- Heading → bold, larger font
- Text → normal paragraph
- Table → formatted grid with header row
- Sections render in order, one after another
- Keep text concise — PDF is for sharing, not for dumping raw data

## Limitations

- No OCR — scanned/image PDFs return empty text
- No form filling — cannot fill PDF form fields
- No watermarking or encryption
- No image extraction from within the PDF
- Table extraction depends on PDF structure — some complex layouts may fail
- generate_pdf creates basic reports — no advanced typography or custom layouts

## Error Patterns

| Error | Meaning | Action |
|---|---|---|
| "PDF is encrypted" | Password-protected file | Ask user for password (not supported yet) |
| "No tables detected" | pdfplumber found no table structures | Try read_pdf for text instead |
| "Page X out of range" | Requested page doesn't exist | Check pdf_metadata for page_count |
| "Not a valid PDF" | File is corrupted or not a PDF | Ask user to re-upload |
