# Red Markdown Dashboard Design

Use this design brief when generating a dashboard from uploaded tabular data.
Keep the interaction and data model in OpenBench A2UI, but make the exported
HTML feel like a compact red executive operations dashboard.

## Layout

- Start with a narrow header, then KPI cards, then two-column analytical panels.
- Prefer dense, scan-friendly sections over a marketing-style hero.
- Use short panel titles and keep tables compact.

## Visual Tokens

- Background: near-white with a faint red tint.
- Accent: deep red for chart marks and small dividers.
- Cards: white, low radius, quiet borders, no heavy shadows.
- Typography: system sans-serif, tabular numbers for KPIs.

```css
:root {
  --ob-bg: #fff5f5;
  --ob-panel: #ffffff;
  --ob-text: #261313;
  --ob-text-secondary: #7f1d1d;
  --ob-border: rgba(185, 28, 28, 0.24);
  --ob-accent: #b91c1c;
}

.ob-dashboard {
  width: min(1240px, calc(100% - 40px));
}

.ob-dashboard__header {
  border-bottom-color: rgba(185, 28, 28, 0.32);
}

.ob-dashboard__eyebrow {
  color: #b91c1c;
  text-transform: uppercase;
}

.ob-kpi,
.ob-panel,
.ob-table-wrap {
  border-radius: 6px;
}

.ob-chart--bar rect,
.ob-chart--line polyline,
.ob-chart--line circle,
.ob-chart--scatter circle,
.slice-0 {
  fill: #b91c1c;
  stroke: #b91c1c;
}
```
