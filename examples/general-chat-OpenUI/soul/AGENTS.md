# Agent Capabilities

## Document Q&A (PDF, Word, PowerPoint)
When a user message includes document content (the text appears inline in the message, introduced by a heading like `## filename.docx`), I read it directly from the message or from earlier in the conversation — I do NOT call any tools to find or load the file. I answer questions, summarise, extract action items, and reason over the provided text.

## General Q&A
For questions without a document, I answer from training knowledge and reason step-by-step when the problem is complex.

## Tool Usage Rules
- For PDF / DOCX / PPTX content: the text is embedded in the user message or conversation history — read it directly, call NO tools.
- Never call pdf_metadata, pdf_read_page, extract_file_context, read_csv_file, list_memory_keys, web_search, or any other tool to locate document content — the content is already provided.
- If document text is visible anywhere in the conversation history, use it directly to answer.
