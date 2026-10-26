# query-explorer

Filter, group, sort, and aggregate over in-memory records without
touching pandas or SQL. Every tool accepts a list of dicts (the standard
payload shape from `data-context-extractor`, `xql`, or any other data
tool) and returns a list of dicts — so operations compose freely in the
agent's reasoning loop.

This is an SDK-level skill: it gives every agent baseline relational
capabilities so project skills can focus on domain logic rather than
re-implementing filter/group/aggregate for the hundredth time.

## Triggers

- User asks "filter by ...", "only show ...", "where ...", "top N"
- User asks to group, bucket, or aggregate data
- User asks "how many", "average", "sum", "min", "max"
- Agent has a list of records and needs to reshape it before charting
  or exporting
- A follow-up question narrows or reshapes the previous turn's output

## Tools

- filter_records: keep rows matching a set of conditions
- sort_records: order rows by one or more keys
- group_and_aggregate: group by one column, aggregate another (sum, mean, count, min, max)
- distinct_values: unique values in a column
- top_n_records: return the N highest rows by a numeric key

## Dependencies

- (none — pure Python stdlib)

## Version

0.1.0
