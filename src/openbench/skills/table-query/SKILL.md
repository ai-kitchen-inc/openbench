# table-query

Answer questions about uploaded spreadsheets and CSVs by running SQL over
them, instead of reading rows as text. Each uploaded data file becomes one
queryable table per sheet; the source card in the conversation lists the
table names, columns, and types.

Raw rows are deliberately kept out of the prompt: a large sheet does not
fit, and eyeballing markdown is the wrong way to compute a total. Run a
query and report the result.

## Triggers

- A source card describes a table and the user asks about its contents
- User asks for a total, average, count, ranking, or percentage
- User asks "how many", "which ... has the most", "break down by ..."
- User asks to filter, group, sort, or compare rows
- User asks what columns or values a data file contains
- A chart or export is requested over uploaded tabular data

## Tools

- list_source_tables: list the tables available in this conversation
- describe_source_table: columns, types, and sample rows for one table
- query_source_table: run read-only SQL and return the rows

## Query Protocol

1. **Read the card first.** It gives the exact table and column names.
   Never invent one.
2. **Compute, do not estimate.** Any number the user asks for comes from a
   query, not from the sample rows on the card.
3. **Describe when unsure.** If a column's meaning or spelling is
   ambiguous, call `describe_source_table` before querying.
4. **Aggregate in SQL.** Return the answer, not the raw table: use
   `GROUP BY`, `SUM`, `COUNT`, `ORDER BY ... LIMIT`. Never `SELECT *` on a
   large table hoping to add it up yourself.
5. **Recover from errors.** A failed query returns the message plus the
   available columns. Read them, fix the query, and retry once.
6. **Report truncation.** If the result says `truncated`, tell the user
   they are seeing a partial result, or re-run with an aggregate.
7. **Say where the number came from.** Name the table and the filter you
   applied so the user can check it.

## References

- `references/duckdb-sql.md` — dialect notes, quoting, dates, and limits

## Dependencies

- duckdb (install `openbench[tabular]`)

## Version

0.1.0
