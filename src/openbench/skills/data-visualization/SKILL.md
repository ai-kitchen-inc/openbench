# data-visualization

Build chart render items that the ChatEngine renders as `ObChart`
components. Every tool in this skill returns a plain dict in the shape
`{"type": "bar"|"line"|"pie"|"scatter"|"area", "title": "...", "data":
[...], "options": {...}}` — the same shape consumed by the default
`ChartRenderer`.

This is the "finish step" for quantitative answers: once the agent has
computed numbers (via query-explorer, xql, or any project skill) it
calls one of these tools to turn those numbers into a visual that the
frontend renders automatically as part of the next assistant turn.

## Triggers

- User asks "show", "chart", "plot", "visualize", "graph"
- User asks for a trend, breakdown, top-N, share, distribution, or comparison
- Agent has computed aggregate data and needs to present it visually
- A previous tool returned a list of records that naturally reads as
  an X/Y series, a category breakdown, or a time series

## References

- chart-types.md: when to use each chart type and what data shape it expects

## Tools

- create_bar_chart: categorical comparison or top-N ranking
- create_line_chart: time series or continuous-axis trend
- create_pie_chart: share-of-total breakdown (max ~8 slices)
- create_scatter_chart: correlation between two numeric fields
- create_area_chart: cumulative or stacked trend

## Dependencies

- (none — pure dict construction)

## Version

0.1.0
