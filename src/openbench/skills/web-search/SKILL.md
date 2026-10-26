# web-search

Search the web for real-time information using Gemini's built-in Google
Search grounding. Returns a synthesized answer with source citations.
Use this whenever the agent needs up-to-date information that is not
available in the uploaded files, reference documents, or its training
data.

This skill wraps OpenBench's `GroundedSearchSource` (which already
handles the Gemini grounding API, source extraction, and redirect URL
resolution) into a tool callable from the agent's reasoning loop.

## Triggers

- User asks about current events, recent publications, or latest standards
- User asks "search for...", "find out...", "what is the latest..."
- Agent needs external context to validate or supplement its answer
  (e.g. checking a regulation number, confirming a conversion factor)
- Agent's knowledge cutoff may not cover the topic
- User references a URL, paper, or external resource by name
- User shares a specific URL and asks to read, open, extract, or
  summarize that page ("baca URL ini", "fetch this link")

## References

- search-guide.md: when to search vs when to use local knowledge

## Tools

- web_search: single query, returns answer + source citations
- web_search_multi: batch multiple queries in one call
- fetch_url: fetch one URL and return readable page text
  (SSRF-guarded — private/local addresses refused; output truncated)

## Dependencies

- google-genai (for Gemini grounding) — already part of openbench[google]

## Version

0.1.0
