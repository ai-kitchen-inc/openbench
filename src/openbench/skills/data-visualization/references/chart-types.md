# Chart Type Reference

Decision guide for picking the right chart type, plus the exact data
shape each one expects.

## Bar Chart — `create_bar_chart`

Use for: categorical comparison, top-N rankings, grouped comparisons.

**Data shape:** `[{"<x_key>": str, "<y_key>": number}, ...]`

**Good for:**
- "Top 10 products by revenue"
- "Emissions by category"
- "Items per quarter"

**Avoid when:** the X-axis is continuous (use line/area instead) or
when you have more than ~20 categories (unreadable).

## Line Chart — `create_line_chart`

Use for: time series, continuous-axis trends.

**Data shape:** `[{"<x_key>": str|number, "<y_key>": number}, ...]`

**Good for:**
- "Revenue over time"
- "Temperature vs pressure curve"
- "Sensor reading by hour"

**Avoid when:** X is categorical and unordered (use bar instead).

## Pie Chart — `create_pie_chart`

Use for: share of total when there are very few categories.

**Data shape:** `[{"<name_key>": str, "<value_key>": number}, ...]`

**Good for:**
- "Budget breakdown: 3-6 line items"
- "Market share among 4 competitors"

**Avoid when:** more than ~8 slices (use a bar chart), or when the
values are negative or could be zero (pie charts can't show those).

## Scatter Chart — `create_scatter_chart`

Use for: correlation or distribution between two numeric variables.

**Data shape:** `[{"<x_key>": number, "<y_key>": number}, ...]`

**Good for:**
- "Energy use vs yield"
- "Price vs rating"

**Avoid when:** either axis is categorical.

## Area Chart — `create_area_chart`

Use for: cumulative totals over time, stacked composition.

**Data shape:** `[{"<x_key>": str|number, "<y_key>": number}, ...]`

**Good for:**
- "Cumulative emissions over years"
- "Running total of shipments"

**Avoid when:** showing discrete events (use bar instead).

## Title Discipline

Every chart should have a title that names the measure AND the scope:

- GOOD: "Q4 2025 Revenue by Region"
- BAD: "Revenue" (what period? what breakdown?)

A good title lets the user understand the chart without reading the
surrounding assistant message.
