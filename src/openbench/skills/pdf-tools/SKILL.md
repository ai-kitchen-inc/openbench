# pdf-tools

Read, analyze, manipulate, and generate PDF documents. Wraps OpenBench's
existing PDF infrastructure (PDFSource, PDFGenerator) plus pdfplumber
for table extraction into agent-callable tools.

Use this skill whenever the user uploads a PDF, asks about PDF contents,
wants to extract tables from a PDF, needs to merge/split documents, or
asks for a PDF report as a deliverable.

## Triggers

Trigger on these regardless of the language the user writes in.

- User uploads or mentions a `.pdf` file
- User asks "what's in this PDF?", "extract tables", "how many pages?"
- User asks to merge, combine, or join multiple PDFs
  (Indonesian: "gabungkan pdf", "satukan pdf")
- User asks to extract specific pages from a PDF
  (Indonesian: "pisahkan pdf", "ambil halaman")
- User asks for a PDF report, summary, or deliverable
  (Indonesian: "unduh sebagai pdf", "buatkan laporan pdf", "ekspor ke pdf",
  "berkas pdf")
- Agent needs structured data from a PDF (tables, metadata)

When the user asks for a PDF file, answering with markdown alone is not
enough — call `generate_pdf` and return the download card. For
spreadsheets use `export_to_excel`; for markdown/text use
`generate_markdown`.

## References

- pdf-guide.md: protocol for reading PDFs, limitations, tips

## Tools

- pdf_metadata: quick info — title, author, pages, size, encrypted status
- read_pdf: full text extraction with page filter + truncation
- read_pdf_page: single page text extraction
- extract_pdf_tables: detect and extract tables → ObTable in chat
- merge_pdfs: combine multiple PDFs into one → ObFileCard
- split_pdf: extract specific pages into a new PDF → ObFileCard
- generate_pdf: create a PDF report from structured sections → ObFileCard

## Protocol

1. ALWAYS call pdf_metadata first — cheap, get page count + encrypted status
2. If encrypted=true → stop, inform user
3. For text extraction:
   - Small PDF (≤20 pages): read_pdf without page filter
   - Large PDF (>20 pages): read_pdf with pages=[specific] or read_pdf_page
4. For tables: extract_pdf_tables (auto-detect, push ObTable)
5. For merge/split: merge_pdfs / split_pdf
6. For report generation: generate_pdf with structured sections
7. NEVER read_pdf on >50 pages without page filter — will blow context window

## Dependencies

- pypdf >= 4.0.0 (already in openbench[data])
- pdfplumber >= 0.10.0 (for table extraction)
- reportlab >= 4.0.0 (already in openbench[output], for generate_pdf)

## Version

0.1.0
