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
- GOOD: "Python 3.13 release date and new features"
- BAD: "tell me about Python"
- GOOD: "US Federal Reserve interest rate decision March 2026"
- BAD: "interest rates"

Include the year or "latest" when looking for recent information:
- "global AI market size 2026"
- "latest React Server Components best practices"

## Source Handling

web_search returns `sources: [{title, url}]`. When citing:
- Include the source title and URL in your response
- If multiple sources agree, mention the consensus
- If sources conflict, note the disagreement
- Never fabricate a URL — only cite what web_search returns
