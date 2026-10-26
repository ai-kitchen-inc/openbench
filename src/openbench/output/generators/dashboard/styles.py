"""Dashboard stylesheet (monochrome, OpenBench design tokens, dark-mode aware)."""

from __future__ import annotations

_DASHBOARD_CSS = """
:root {
  color-scheme: light dark;
  --ob-bg: #ffffff;
  --ob-text: #1a1a1a;
  --ob-text-secondary: rgba(26, 26, 26, 0.66);
  --ob-border: rgba(0, 0, 0, 0.08);
  --ob-panel: #ffffff;
  --ob-muted: rgba(0, 0, 0, 0.035);
  --ob-accent: #1f63c6;
}
/* Dark palette mirrors the @openbench/chat-ui app tokens. Applies when the OS
   prefers dark (standalone / public /d/{id} page) or when the host sets an
   explicit data-theme on the document (in-app preview). */
:root[data-theme="dark"] {
  --ob-bg: #191919;
  --ob-text: #e3e2de;
  --ob-text-secondary: #9b9a97;
  --ob-border: rgba(255, 255, 255, 0.09);
  --ob-panel: #202020;
  --ob-muted: rgba(255, 255, 255, 0.045);
  --ob-accent: #4f9bff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ob-bg: #191919;
    --ob-text: #e3e2de;
    --ob-text-secondary: #9b9a97;
    --ob-border: rgba(255, 255, 255, 0.09);
    --ob-panel: #202020;
    --ob-muted: rgba(255, 255, 255, 0.045);
    --ob-accent: #4f9bff;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--ob-bg);
  color: var(--ob-text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
.ob-dashboard {
  width: min(1180px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0 32px;
}
.ob-dashboard__header {
  padding: 0 0 18px;
  border-bottom: 1px solid var(--ob-border);
}
.ob-dashboard__eyebrow {
  margin-bottom: 8px;
  color: var(--ob-text-secondary);
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0;
}
h1, h2, h3, p { margin: 0; }
h1 { font-size: 28px; line-height: 1.15; letter-spacing: 0; }
h2 { font-size: 18px; letter-spacing: 0; }
h3 { font-size: 14px; letter-spacing: 0; }
.ob-dashboard__description,
.ob-section__description,
.ob-panel__description,
.ob-kpi__note,
.ob-footer {
  color: var(--ob-text-secondary);
}
.ob-dashboard__description { max-width: 760px; margin-top: 8px; }
.ob-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  padding: 18px 0;
}
.ob-kpi {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--ob-border);
  border-radius: 8px;
  background: var(--ob-panel);
}
.ob-kpi__label {
  color: var(--ob-text-secondary);
  font-size: 12px;
  font-weight: 600;
}
.ob-kpi__value {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 8px;
  font-size: 26px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
}
.ob-kpi__value span,
.ob-kpi__delta {
  color: var(--ob-text-secondary);
  font-size: 12px;
  font-weight: 500;
}
.ob-kpi__delta { display: inline-block; margin-top: 6px; }
.ob-kpi__note { margin-top: 6px; font-size: 12px; }
.ob-section {
  padding-top: 18px;
  border-top: 1px solid var(--ob-border);
}
.ob-section:first-of-type { border-top: 0; }
.ob-section__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.ob-panel-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 12px;
}
.ob-panel {
  grid-column: span 6;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--ob-border);
  border-radius: 8px;
  background: var(--ob-panel);
}
.ob-panel--table,
.ob-panel--text { grid-column: span 12; }
.ob-panel__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.ob-chart {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}
.ob-chart line {
  stroke: rgba(0, 0, 0, 0.18);
  stroke-width: 1;
}
.ob-chart text {
  fill: var(--ob-text-secondary);
  font-size: 11px;
}
.ob-chart--bar rect {
  fill: #1f63c6;
}
.ob-chart--line polyline {
  fill: none;
  stroke: #1f63c6;
  stroke-width: 2.5;
}
.ob-chart--line circle,
.ob-chart--scatter circle {
  fill: #ffffff;
  stroke: #1f63c6;
  stroke-width: 2;
}
.ob-chart--line .area {
  fill: rgba(31, 99, 198, 0.12);
  stroke: none;
}
.ob-chart--pie path { stroke: #ffffff; stroke-width: 2; }
.slice-0, .ob-legend span[style*="--i:0"] { fill: #1f63c6; background: #1f63c6; }
.slice-1, .ob-legend span[style*="--i:1"] { fill: #0f8268; background: #0f8268; }
.slice-2, .ob-legend span[style*="--i:2"] { fill: #9b6a00; background: #9b6a00; }
.slice-3, .ob-legend span[style*="--i:3"] { fill: #8d4bb3; background: #8d4bb3; }
.slice-4, .ob-legend span[style*="--i:4"] { fill: #b02020; background: #b02020; }
.slice-5, .ob-legend span[style*="--i:5"] { fill: #5f6f7d; background: #5f6f7d; }
.slice-6, .ob-legend span[style*="--i:6"] { fill: #2f6f8f; background: #2f6f8f; }
.slice-7, .ob-legend span[style*="--i:7"] { fill: #6b7f2a; background: #6b7f2a; }
.slice-8, .ob-legend span[style*="--i:8"] { fill: #7b5c43; background: #7b5c43; }
.slice-9, .ob-legend span[style*="--i:9"] { fill: #4f5aa8; background: #4f5aa8; }
.ob-pie-layout {
  display: grid;
  grid-template-columns: minmax(180px, 320px) minmax(160px, 1fr);
  gap: 12px;
  align-items: center;
}
.ob-legend { display: grid; gap: 7px; }
.ob-legend__item {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) max-content;
  align-items: center;
  gap: 8px;
  color: var(--ob-text-secondary);
  font-size: 12px;
}
.ob-legend__item span {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.ob-legend__item strong {
  overflow: hidden;
  color: var(--ob-text);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ob-legend__item em {
  font-style: normal;
  font-variant-numeric: tabular-nums;
}
.ob-table-wrap {
  overflow: auto;
  border: 1px solid var(--ob-border);
  border-radius: 6px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
th, td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--ob-border);
  text-align: left;
  white-space: nowrap;
}
th {
  background: var(--ob-muted);
  color: var(--ob-text-secondary);
  font-weight: 650;
}
tr:last-child td { border-bottom: 0; }
.ob-empty {
  display: flex;
  min-height: 220px;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--ob-border);
  border-radius: 6px;
  color: var(--ob-text-secondary);
}
.ob-footer {
  margin-top: 24px;
  padding-top: 12px;
  border-top: 1px solid var(--ob-border);
  font-size: 12px;
}
@media (max-width: 860px) {
  .ob-dashboard { width: min(100% - 24px, 1180px); padding-top: 18px; }
  h1 { font-size: 23px; }
  .ob-section__heading,
  .ob-panel__header { display: block; }
  .ob-panel { grid-column: span 12; }
  .ob-pie-layout { grid-template-columns: 1fr; }
}
"""
