# When to Search vs When to Use Local Knowledge

## Use web_search when:

- The question is about something that happened AFTER your training cutoff
- The user explicitly asks to search or verify online
- You need a specific number (exchange rate, population, stock price)
  that changes over time
- You are unsure about a fact and want to ground your answer
- The topic involves recent regulations, standards updates, or
  newly published research

## Do NOT search when:

- The answer is already in the uploaded files or skill references
- The question is about the user's own data (use xql or other data tools)
- You are confident in your answer from training data and the topic
  is not time-sensitive
- The user is asking for an opinion, not a fact

## Query Tips

Good queries are specific and factual:
- GOOD: "ISO 14040:2006 amendment 1 publication date"
- BAD: "tell me about ISO 14040"
- GOOD: "Indonesia PROPER 2025 evaluation criteria update"
- BAD: "PROPER rating"

Include the year or "latest" when looking for recent information:
- "renewable energy market size 2026"
- "latest IPCC emission factors for cement production"

## Source Handling

web_search returns `sources: [{title, url}]`. When citing:
- Include the source title and URL in your response
- If multiple sources agree, mention the consensus
- If sources conflict, note the disagreement
- Never fabricate a URL — only cite what web_search returns
