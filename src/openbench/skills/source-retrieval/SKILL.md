# source-retrieval

Search inside the user's uploaded documents and read the parts that
matter, instead of receiving every document's full text in the prompt.
Each source in this conversation is summarized by a short card listing
its name, id, outline, and summary; these tools fetch the actual passages
on demand.

This is an SDK-level skill. The host application decides which sources
are in scope for the current turn — you cannot reach another user's or
another session's documents, and asking for an id that is not on a card
returns an error.

## Triggers

- A source card is present and the user asks anything about that document
- User asks "what does the document say about ...", "find ... in the file"
- User asks to quote, cite, or locate a passage
- The eagerly retrieved passages in context are not enough to answer
- User asks about a section named in a card's outline
- A follow-up question goes deeper into a document already discussed

## Tools

- search_sources: find the passages most relevant to a query
- read_source_section: read consecutive passages from one source
- outline_source: list a document's headings and where each begins

## Retrieval Protocol

1. **Read the cards first.** They tell you which sources exist, what each
   one is, and its id. Never guess an id.
2. **Search before answering.** If the passages already in context do not
   contain the answer, call `search_sources` with the user's own wording.
   Do not answer a document question from memory or assumption.
3. **Widen, then narrow.** If a search returns nothing useful, retry with
   different words — a synonym, the term in the document's own language,
   or a phrase from the outline. If it still returns nothing, say the
   document does not appear to cover it rather than inventing an answer.
4. **Read around a hit.** A search result carries `chunk_index`. Call
   `read_source_section(source_id, start_chunk=<index - 1>, chunk_count=3)`
   when the passage is cut off or you need surrounding context.
5. **Scope deliberately.** Pass `source_ids` when the user names a
   specific document. Omit it to search everything in scope.
6. **Cite what you used.** Name the source, and the heading or page when
   the result carries one, so the user can verify it.
7. **Be honest about coverage.** If a source's card says it is still
   indexing, or a tool returns an error, tell the user which document you
   could not consult before you answer.

## Dependencies

- (none — the host application injects the index)

## Version

0.1.0
