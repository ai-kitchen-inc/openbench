/**
 * ObDashboardFrame - OpenBench native dashboard renderer.
 */

import { useEffect, useRef, useState } from "react";
import { useChatContextOptional } from "../../components/ChatProvider";
import { formatFileSize } from "../../core/utils";
import type { A2UIComponent, A2UIComponentRenderer, A2UISurface } from "../../types";
import { resolveNumber, resolveString, resolveValue } from "../data-binding";
import { ObChart } from "./ob-chart";
import { ObTable } from "./ob-table";

type DashboardRecord = Record<string, unknown>;
type DashboardDatasets = Record<string, DashboardRecord[]>;
type TableColumn = { key: string; header: string };

function MonitorIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8" />
      <path d="M12 16v4" />
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </svg>
  );
}

function isRecord(value: unknown): value is DashboardRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeComponentProperties(component: A2UIComponent): A2UIComponent {
  const nestedProperties = isRecord(component.properties) ? component.properties : undefined;
  if (!nestedProperties) return component;

  const { properties: _properties, ...flatComponent } = component;
  return {
    ...nestedProperties,
    ...flatComponent,
    id: component.id,
    component: component.component,
  } as A2UIComponent;
}

function parseViewModel(value: unknown): DashboardRecord | undefined {
  if (isRecord(value)) return value;
  if (typeof value !== "string") return undefined;
  try {
    const parsed = JSON.parse(value);
    return isRecord(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function toRows(value: unknown): DashboardRecord[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord);
}

function normalizeDatasets(value: unknown): DashboardDatasets {
  if (!isRecord(value)) return {};
  const result: DashboardDatasets = {};
  for (const [key, rows] of Object.entries(value)) {
    result[key] = recordsFromValue(rows);
  }
  return result;
}

function stringValue(value: unknown, fallback = ""): string {
  if (value == null) return fallback;
  const text = String(value);
  return text ? text : fallback;
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => stringValue(item)).filter(Boolean);
  }
  const text = stringValue(value);
  return text ? [text] : [];
}

function templateRecord(value: unknown): DashboardRecord | undefined {
  if (isRecord(value)) return value;
  if (typeof value !== "string") return undefined;
  try {
    const parsed = JSON.parse(value);
    return isRecord(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function templateFormatFrom(component: DashboardRecord): string {
  const direct = stringValue(component.templateFormat ?? component.template_format).toLowerCase();
  if (direct) return direct;
  const custom = templateRecord(component.customTemplate ?? component.custom_template);
  return stringValue(custom?.format).toLowerCase();
}

function templateSourceFrom(component: DashboardRecord, format: string): string {
  const direct = stringValue(component.templateSource ?? component.template_source).toLowerCase();
  if (direct) return direct;
  return format ? "user" : "default";
}

function columnString(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function normalizeTableColumns(value: unknown, data: DashboardRecord[]): TableColumn[] {
  const rawColumns = Array.isArray(value) && value.length > 0 ? value : data[0] ? Object.keys(data[0]) : [];
  return rawColumns
    .map((column): TableColumn | null => {
      if (isRecord(column)) {
        const key = columnString(
          column.key ??
            column.field ??
            column.id ??
            column.name ??
            column.accessor ??
            column.dataKey ??
            column.value,
        );
        const header = columnString(
          column.label ?? column.header ?? column.title ?? column.name ?? column.key ?? column.field,
        );
        const resolvedKey = key || header;
        if (!resolvedKey) return null;
        return { key: resolvedKey, header: header || resolvedKey };
      }
      const text = columnString(column);
      return text ? { key: text, header: text } : null;
    })
    .filter((column): column is TableColumn => column !== null);
}

function stableKey(value: DashboardRecord, fallback: string): string {
  const explicit = stringValue(value.id ?? value.key ?? value.name);
  if (explicit) return explicit;
  try {
    const serialized = JSON.stringify(value);
    return serialized ? serialized : fallback;
  } catch {
    return fallback;
  }
}

function componentParameters(component: DashboardRecord): DashboardRecord {
  const merged: DashboardRecord = {};
  for (const key of ["props", "parameters", "content", "value", "view_model", "options"]) {
    const nested = component[key];
    if (isRecord(nested)) Object.assign(merged, nested);
  }
  for (const [key, value] of Object.entries(component)) {
    if (["props", "parameters", "content", "value", "view_model", "options"].includes(key) && isRecord(value)) continue;
    if ((key === "type" || key === "component" || key === "kind") && merged[key] !== undefined) {
      merged[`component_${key}`] = value;
      continue;
    }
    merged[key] = value;
  }
  return merged;
}

function withDataControls(item: DashboardRecord): DashboardRecord {
  const data = item.data;
  if (!isRecord(data) || chartJsRecords(data).rows.length > 0 || recordsFromValue(data).length > 0) {
    return item;
  }
  const merged: DashboardRecord = { ...item };
  for (const [key, value] of Object.entries(data)) {
    if (merged[key] === undefined) merged[key] = value;
  }
  if (data.label !== undefined && merged.x === undefined && merged.x_field === undefined) {
    merged.x = data.label;
  }
  if (data.value !== undefined && merged.y === undefined && merged.y_field === undefined) {
    merged.y = data.value;
  }
  return merged;
}

function normalizedChartType(value: unknown): string {
  const requested = stringValue(value, "bar").toLowerCase();
  const aliases: Record<string, string> = {
    bar_chart: "bar",
    column: "bar",
    column_chart: "bar",
    line_chart: "line",
    area_chart: "area",
    pie_chart: "pie",
    scatter_chart: "scatter",
  };
  return aliases[requested] ?? requested.replace(/_chart$/, "");
}

function normalizeDashboardComponentItem(component: DashboardRecord): DashboardRecord | null {
  let rawType = stringValue(component.type ?? component.component ?? component.kind).toLowerCase();
  const merged = withDataControls(componentParameters(component));
  if (!rawType) {
    if (merged.chart_type ?? merged.chartType ?? merged.visualization) rawType = "chart";
    if ((merged.data || merged.dataset_id || merged.dataset) && merged.columns) rawType = "table";
  }
  if (["kpi", "metric", "stat", "stat_card", "metric_card", "kpi_card"].includes(rawType)) {
    return {
      ...merged,
      type: "kpi",
      label: merged.label ?? merged.title ?? merged.name ?? "KPI",
    };
  }
  if (
    [
      "chart",
      "bar",
      "bar_chart",
      "column",
      "column_chart",
      "line",
      "line_chart",
      "area",
      "area_chart",
      "pie",
      "pie_chart",
      "scatter",
      "scatter_chart",
    ].includes(rawType)
  ) {
    return {
      ...merged,
      type: "chart",
      chart_type: normalizedChartType(
        merged.chart_type ??
          merged.chartType ??
          merged.visualization ??
          merged.visualizationType ??
          (rawType === "chart" ? merged.type : undefined) ??
          rawType,
      ),
    };
  }
  if (rawType === "kpi_grid") {
    return { ...merged, type: "kpi_grid" };
  }
  if (["table", "data_table", "text", "markdown", "summary"].includes(rawType)) {
    return { ...merged, type: rawType };
  }
  return Object.keys(merged).length > 0 ? merged : null;
}

function componentChildItems(component: DashboardRecord): DashboardRecord[] {
  const columnItems = Array.isArray(component.columns) ? component.columns : undefined;
  return toRows(
    component.items ??
      component.components ??
      component.panels ??
      component.charts ??
      component.widgets ??
      component.cards,
  ).concat(toRows(component.children)).concat(toRows(columnItems));
}

function kpisFromGrid(component: DashboardRecord): DashboardRecord[] {
  const merged = componentParameters(component);
  const data = isRecord(merged.data) ? merged.data : {};
  const values = toRows(data.values ?? merged.values ?? merged.items);
  return values.map((value) => normalizeDashboardComponentItem({ ...value, type: "kpi" })).filter(
    (item): item is DashboardRecord => item !== null,
  );
}

function isComponentContainer(component: DashboardRecord): boolean {
  const rawType = stringValue(component.type ?? component.component ?? component.kind).toLowerCase();
  return ["section", "group", "container", "row", "column", "columns", "grid"].includes(rawType);
}

function flattenDashboardComponentItems(components: DashboardRecord[]): DashboardRecord[] {
  const items: DashboardRecord[] = [];
  for (const component of components) {
    const children = componentChildItems(component);
    if (children.length > 0 && isComponentContainer(component)) {
      items.push(...flattenDashboardComponentItems(children));
      continue;
    }
    const normalized = normalizeDashboardComponentItem(component);
    if (normalized?.type === "kpi_grid") {
      items.push(...kpisFromGrid(component));
      continue;
    }
    if (normalized) items.push(normalized);
  }
  return items;
}

function componentHasHeading(component: DashboardRecord): boolean {
  const merged = componentParameters(component);
  return Boolean(merged.title ?? merged.name ?? merged.label ?? merged.description);
}

function componentSectionTitle(component: DashboardRecord): string {
  const merged = componentParameters(component);
  return stringValue(merged.title ?? merged.name ?? merged.label, "Dashboard");
}

function componentsToLayout(value: unknown): {
  kpis: DashboardRecord[];
  panels: DashboardRecord[];
  sections: DashboardRecord[];
} {
  const kpis: DashboardRecord[] = [];
  const panels: DashboardRecord[] = [];
  const sections: DashboardRecord[] = [];
  for (const component of toRows(value)) {
    const children = componentChildItems(component);
    if (children.length > 0 && isComponentContainer(component)) {
      const childItems = flattenDashboardComponentItems(children);
      const childKpis = childItems.filter((item) => item.type === "kpi");
      const childPanels = childItems.filter((item) => item.type !== "kpi");
      kpis.push(...childKpis);
      if (childPanels.length > 0 && componentHasHeading(component)) {
        const merged = componentParameters(component);
        sections.push({
          title: componentSectionTitle(component),
          description: merged.description ?? "",
          items: childPanels,
        });
      } else {
        panels.push(...childPanels);
      }
      continue;
    }
    const normalized = normalizeDashboardComponentItem(component);
    if (!normalized) continue;
    if (normalized.type === "kpi_grid") {
      kpis.push(...kpisFromGrid(component));
      continue;
    }
    if (normalized.type === "kpi") {
      kpis.push(normalized);
    } else {
      panels.push(normalized);
    }
  }
  return { kpis, panels, sections };
}

function formatDashboardValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => formatDashboardValue(item)).filter(Boolean).join(", ");
  }
  if (isRecord(value)) {
    const preferred = value.value ?? value.label ?? value.name ?? value.title;
    if (preferred !== undefined) return formatDashboardValue(preferred);
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value);
}

function isNumberLike(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") {
    const text = value.replace(/,/g, "").trim();
    return text !== "" && Number.isFinite(Number(text));
  }
  return false;
}

function firstNonNull(records: DashboardRecord[], key: string): unknown {
  for (const row of records) {
    if (row[key] != null) return row[key];
  }
  return undefined;
}

/** First non-numeric column — the natural x-axis / label. */
function firstCategoryKey(records: DashboardRecord[]): string {
  const row = records[0];
  if (!row) return "name";
  const keys = Object.keys(row);
  for (const key of keys) {
    const value = firstNonNull(records, key);
    if (value != null && !isNumberLike(value)) return key;
  }
  return keys[0] ?? "name";
}

function firstNumericKey(records: DashboardRecord[], fallback: string): string {
  let firstNumeric: string | null = null;
  for (const row of records) {
    for (const key of Object.keys(row)) {
      if (!isNumberLike(row[key])) continue;
      if (firstNumeric === null) firstNumeric = key;
      if (key !== fallback) return key;
    }
  }
  return firstNumeric ?? fallback;
}

function tableCellValue(row: DashboardRecord, column: TableColumn): unknown {
  if (Object.prototype.hasOwnProperty.call(row, column.key)) return row[column.key];
  if (Object.prototype.hasOwnProperty.call(row, column.header)) return row[column.header];
  return undefined;
}

function safeFieldName(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "value";
}

function chartJsRecords(value: unknown): { rows: DashboardRecord[]; xKey: string; yKey: string } {
  if (!isRecord(value) || !Array.isArray(value.labels) || !Array.isArray(value.datasets)) {
    return { rows: [], xKey: "label", yKey: "value" };
  }
  const datasets = value.datasets.filter(isRecord);
  if (datasets.length === 0) return { rows: [], xKey: "label", yKey: "value" };
  const keys = datasets.map((dataset, index) =>
    safeFieldName(stringValue(dataset.label, `value_${index + 1}`)),
  );
  const rows = value.labels.map((label, index) => {
    const row: DashboardRecord = { label };
    datasets.forEach((dataset, datasetIndex) => {
      const values = Array.isArray(dataset.data) ? dataset.data : [];
      row[keys[datasetIndex] ?? `value_${datasetIndex + 1}`] = values[index];
    });
    return row;
  });
  return { rows, xKey: "label", yKey: keys[0] ?? "value" };
}

function recordsFromValue(value: unknown): DashboardRecord[] {
  const directRows = toRows(value);
  if (directRows.length > 0) return directRows;
  const chartJs = chartJsRecords(value);
  if (chartJs.rows.length > 0) return chartJs.rows;
  if (isRecord(value)) {
    for (const key of ["values", "records", "rows", "data", "groups"]) {
      const nestedRows = recordsFromValue(value[key]);
      if (nestedRows.length > 0) return nestedRows;
    }
  }
  return [];
}

function fieldFromAxis(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (isRecord(value)) {
    for (const key of ["property", "field", "key", "dataKey", "name", "id", "value", "column"]) {
      if (value[key] != null) return stringValue(value[key]);
    }
  }
  return "";
}

function axisField(panel: DashboardRecord, keys: string[], optionKeys: string[]): string {
  for (const key of keys) {
    const value = fieldFromAxis(panel[key]);
    if (value) return value;
  }
  const options = isRecord(panel.options) ? panel.options : {};
  for (const key of optionKeys) {
    const value = fieldFromAxis(options[key]);
    if (value) return value;
  }
  return "";
}

function resolvePanelData(panel: DashboardRecord, datasets: DashboardDatasets): DashboardRecord[] {
  const directRows = recordsFromValue(panel.data ?? panel.records ?? panel.values);
  if (directRows.length > 0) return directRows;

  const datasetKey = stringValue(
    (typeof panel.data === "string" ? panel.data : undefined) ??
    (isRecord(panel.data) ? panel.data.dataset_id ?? panel.data.datasetId ?? panel.data.dataset : undefined) ??
    panel.dataset ??
      panel.dataset_id ??
      panel.datasetId ??
      panel.dataKey ??
      panel.source_dataset ??
      panel.sourceDataset ??
      panel.source,
  );
  if (datasetKey && datasets[datasetKey]) return datasets[datasetKey];
  return [];
}

function panelItems(section: DashboardRecord): DashboardRecord[] {
  return toRows(
    section.items ??
      section.components ??
      section.panels ??
      section.charts ??
      section.widgets ??
      section.cards,
  );
}

function sectionsFrom(value: unknown, fallbackItems: unknown): DashboardRecord[] {
  const sections = toRows(value);
  if (sections.length > 0 && sections.some((section) => panelItems(section).length > 0)) {
    return sections;
  }

  const items = toRows(fallbackItems);
  return items.length > 0 ? [{ title: "Dashboard", items }] : [];
}

function sectionsContainComponentContainers(value: unknown): boolean {
  return toRows(value).some((section) =>
    panelItems(section).some(
      (item) => componentChildItems(item).length > 0 && isComponentContainer(item),
    ),
  );
}

function sectionsHaveOnlyEmptyCharts(value: unknown): boolean {
  const sections = toRows(value);
  const items = sections.flatMap(panelItems);
  return (
    items.length > 0 &&
    items.every((item) => {
      if (stringValue(item.type ?? item.component ?? item.kind).toLowerCase() !== "chart") return false;
      return recordsFromValue(item.data ?? item.records).length === 0;
    })
  );
}

function titleFromDatasetId(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function panelsFromDatasets(datasets: DashboardDatasets): DashboardRecord[] {
  const panels: DashboardRecord[] = [];
  for (const [datasetId, records] of Object.entries(datasets)) {
    if (
      records.length === 0 ||
      ["kpis", "kpi", "metrics", "stats"].includes(datasetId.toLowerCase())
    ) {
      continue;
    }
    const xField = firstCategoryKey(records);
    const yField = firstNumericKey(records, xField);
    if (!xField || !yField || xField === yField) continue;
    panels.push({
      type: "chart",
      chart_type: /date|month|year|week|day|time/i.test(xField) ? "line" : "bar",
      title: titleFromDatasetId(datasetId),
      data: records,
      dataset: datasetId,
      x_field: xField,
      y_field: yField,
    });
    if (panels.length >= 4) break;
  }
  return panels;
}

function shouldSynthesizePanelsFromDatasets(datasets: DashboardDatasets): boolean {
  let viable = 0;
  for (const [datasetId, records] of Object.entries(datasets)) {
    if (
      records.length === 0 ||
      ["kpis", "kpi", "metrics", "stats"].includes(datasetId.toLowerCase())
    ) {
      continue;
    }
    const xField = firstCategoryKey(records);
    const yField = firstNumericKey(records, xField);
    if (xField && yField && xField !== yField) viable += 1;
    if (viable >= 2) return true;
  }
  return false;
}

function panelKind(panel: DashboardRecord): string {
  return stringValue(panel.type ?? panel.component ?? panel.kind, "chart").toLowerCase();
}

function chartType(panel: DashboardRecord): string {
  const requested = stringValue(
    panel.chart_type ?? panel.chartType ?? panel.visualization ?? panel.visualizationType ?? panel.type,
    "bar",
  ).toLowerCase();
  const normalized = normalizedChartType(requested);
  return ["bar", "line", "pie", "scatter", "area"].includes(normalized) ? normalized : "bar";
}

function maxRows(panel: DashboardRecord): number {
  const value = Number(panel.max_rows ?? panel.maxRows ?? 20);
  return Number.isFinite(value) && value > 0 ? value : 20;
}

function ShareIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="M7 10l5 5 5-5" />
      <path d="M12 15V3" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function FileTextIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M16 13H8" />
      <path d="M16 17H8" />
      <path d="M10 9H8" />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function slugify(value: string): string {
  const cleaned = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return cleaned.slice(0, 48) || "dashboard";
}

function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function downloadJson(filename: string, data: unknown): void {
  downloadBlob(filename, new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
}

function HeaderActions({ viewModel, title }: { viewModel: unknown; title: string }) {
  const actions = useChatContextOptional()?.dashboardActions;
  const [busy, setBusy] = useState<"publish" | "export" | "pdf" | null>(null);
  const [publishedUrl, setPublishedUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  // Close the export menu on outside click / Escape.
  useEffect(() => {
    if (!exportOpen) return;
    function onPointerDown(event: PointerEvent) {
      if (!exportRef.current?.contains(event.target as Node)) setExportOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setExportOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [exportOpen]);

  if (!actions || (!actions.publish && !actions.exportGrafana && !actions.exportPdf)) return null;

  const canExport = Boolean(actions.exportGrafana || actions.exportPdf);

  async function handlePublish() {
    if (!actions?.publish) return;
    setBusy("publish");
    setError(null);
    setCopied(false);
    try {
      const result = await actions.publish(viewModel);
      setPublishedUrl(result?.url ?? null);
    } catch {
      setError("Publish failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleExport() {
    if (!actions?.exportGrafana) return;
    setExportOpen(false);
    setBusy("export");
    setError(null);
    try {
      const model = await actions.exportGrafana(viewModel);
      downloadJson(`${slugify(title)}.grafana.json`, model);
    } catch {
      setError("Export failed");
    } finally {
      setBusy(null);
    }
  }

  async function handlePdf() {
    if (!actions?.exportPdf) return;
    setExportOpen(false);
    setBusy("pdf");
    setError(null);
    try {
      const blob = await actions.exportPdf(viewModel);
      downloadBlob(`${slugify(title)}.pdf`, blob);
    } catch {
      setError("PDF export failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleCopy() {
    if (!publishedUrl) return;
    try {
      await navigator.clipboard?.writeText(publishedUrl);
      setCopied(true);
    } catch {
      setError("Copy failed");
    }
  }

  return (
    <div className="ob-dashboard-frame__actions">
      <div className="ob-dashboard-frame__action-row">
        {actions.publish && (
          <button
            type="button"
            className="ob-dashboard-frame__action"
            onClick={handlePublish}
            disabled={busy !== null}
          >
            <ShareIcon />
            {busy === "publish" ? "Publishing…" : "Publish"}
          </button>
        )}
        {canExport && (
          <div className="ob-dashboard-frame__export" ref={exportRef}>
            <button
              type="button"
              className="ob-dashboard-frame__action"
              onClick={() => setExportOpen((open) => !open)}
              disabled={busy !== null}
              aria-haspopup="menu"
              aria-expanded={exportOpen}
            >
              <DownloadIcon />
              {busy === "export" || busy === "pdf" ? "Exporting…" : "Export"}
              <ChevronDownIcon />
            </button>
            {exportOpen && (
              <div className="ob-dashboard-frame__export-menu" role="menu">
                {actions.exportGrafana && (
                  <button
                    type="button"
                    className="ob-dashboard-frame__export-item"
                    role="menuitem"
                    onClick={handleExport}
                  >
                    <DownloadIcon />
                    Grafana JSON
                  </button>
                )}
                {actions.exportPdf && (
                  <button
                    type="button"
                    className="ob-dashboard-frame__export-item"
                    role="menuitem"
                    onClick={handlePdf}
                  >
                    <FileTextIcon />
                    PDF
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>
      {publishedUrl && (
        <div className="ob-dashboard-frame__share-link">
          <a href={publishedUrl} target="_blank" rel="noopener noreferrer">
            {publishedUrl}
          </a>
          <button
            type="button"
            className="ob-dashboard-frame__copy"
            onClick={handleCopy}
            aria-label="Copy share link"
          >
            <CopyIcon />
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      )}
      {error && <div className="ob-dashboard-frame__action-error">{error}</div>}
    </div>
  );
}

function clampPreviewHeight(height: number): string {
  return `${Math.max(260, Math.min(height, 720))}px`;
}

/**
 * Stamp the app's resolved theme onto the standalone dashboard HTML so the
 * sandboxed preview matches the app (the generated CSS honors
 * ``<html data-theme>``). Reads the document's data-theme; if absent the HTML
 * falls back to ``prefers-color-scheme`` on its own.
 */
function applyThemeToHtml(html: string): string {
  if (typeof document === "undefined") return html;
  const theme = document.documentElement.getAttribute("data-theme");
  if (theme !== "dark" && theme !== "light") return html;
  return html.replace(/<html(\s[^>]*)?>/i, (match, attrs = "") => {
    if (/\sdata-theme=/i.test(match)) return match;
    return `<html${attrs} data-theme="${theme}">`;
  });
}

/**
 * "Open" control. When the host provides an authenticated ``loadHtml``,
 * fetch the HTML and open it as a blob (the raw URL is auth-protected and a
 * plain anchor / new tab can't attach the bearer token). Otherwise fall back
 * to a normal link, which works in no-auth/local setups.
 */
function OpenDashboardLink({ url }: { url: string }) {
  const loadHtml = useChatContextOptional()?.dashboardActions?.loadHtml;
  const [busy, setBusy] = useState(false);

  if (!loadHtml) {
    return (
      <a
        className="ob-dashboard-frame__open"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
      >
        <ExternalLinkIcon />
        Open
      </a>
    );
  }

  async function handleOpen() {
    if (!loadHtml) return;
    setBusy(true);
    try {
      const html = await loadHtml(url);
      const blobUrl = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      window.open(blobUrl, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
    } catch {
      // Surface nothing intrusive; the inline preview already shows errors.
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className="ob-dashboard-frame__open"
      onClick={handleOpen}
      disabled={busy}
    >
      <ExternalLinkIcon />
      {busy ? "Opening…" : "Open"}
    </button>
  );
}

/**
 * Inline preview for the exported dashboard HTML. When ``loadHtml`` is available,
 * fetch the authenticated HTML and render it via a sandboxed ``srcDoc`` iframe
 * (a bare ``src`` to an auth-protected URL 401s and renders blank/black).
 */
function HtmlFallbackPreview({
  url,
  title,
  height,
}: {
  url: string;
  title: string;
  height: number;
}) {
  const loadHtml = useChatContextOptional()?.dashboardActions?.loadHtml;
  const [html, setHtml] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const style = { height: clampPreviewHeight(height) };

  useEffect(() => {
    if (!loadHtml) return;
    let cancelled = false;
    setState("loading");
    loadHtml(url)
      .then((text) => {
        if (!cancelled) {
          setHtml(applyThemeToHtml(text));
          setState("idle");
        }
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [loadHtml, url]);

  if (!loadHtml) {
    return (
      <iframe title={title} src={url} className="ob-dashboard-frame__iframe" style={style} />
    );
  }
  if (state === "error") {
    return <div className="ob-dashboard-frame__empty">Couldn't load dashboard preview.</div>;
  }
  if (html == null) {
    return <div className="ob-dashboard-frame__empty">Loading preview…</div>;
  }
  return (
    <iframe
      title={title}
      srcDoc={html}
      sandbox=""
      className="ob-dashboard-frame__iframe"
      style={style}
    />
  );
}

function NativeHeader({
  title,
  description,
  dashboardUrl,
  fileName,
  fileSize,
  viewModel,
}: {
  title: string;
  description: string;
  dashboardUrl: string;
  fileName: string;
  fileSize?: number;
  viewModel?: unknown;
}) {
  return (
    <header className="ob-dashboard-frame__header">
      <span className="ob-dashboard-frame__icon">
        <MonitorIcon />
      </span>
      <div className="ob-dashboard-frame__title-wrap">
        <h2 className="ob-dashboard-frame__title">{title}</h2>
        {description && <p className="ob-dashboard-frame__description">{description}</p>}
        {dashboardUrl && (
          <div className="ob-dashboard-frame__meta">
            {fileName}
            {fileSize != null ? ` - ${formatFileSize(fileSize)}` : ""}
          </div>
        )}
      </div>
      <div className="ob-dashboard-frame__header-actions">
        {dashboardUrl && <OpenDashboardLink url={dashboardUrl} />}
        {viewModel != null && <HeaderActions viewModel={viewModel} title={title} />}
      </div>
    </header>
  );
}

function resolveKpiValue(item: DashboardRecord, datasets: DashboardDatasets): unknown {
  if (item.value != null) return item.value;
  const datasetKey = stringValue(item.dataset_id ?? item.dataset ?? item.source);
  const column = stringValue(
    item.value_column ?? item.value_key ?? item.column ?? item.field,
  );
  if (datasetKey && column) {
    const records = datasets[datasetKey];
    const row = records?.[0];
    if (row && Object.prototype.hasOwnProperty.call(row, column)) return row[column];
  }
  return undefined;
}

function formatKpiValue(item: DashboardRecord, datasets: DashboardDatasets): string {
  const text = formatDashboardValue(resolveKpiValue(item, datasets));
  if (!text) return "";
  const fmt = stringValue(item.format ?? item.value_format ?? item.valueFormat);
  const variant = stringValue(item.variant ?? item.type).toLowerCase();
  if ((fmt.includes("$") || ["currency", "money", "usd"].includes(variant)) && !text.startsWith("$")) {
    return `$${text}`;
  }
  if (fmt.includes("%") && !text.endsWith("%")) return `${text}%`;
  return text;
}

function KpiCard({
  item,
  index,
  datasets,
}: {
  item: DashboardRecord;
  index: number;
  datasets: DashboardDatasets;
}) {
  const label = stringValue(item.label ?? item.title, `KPI ${index + 1}`);
  const value = formatKpiValue(item, datasets);
  const unit = stringValue(item.unit);
  const delta = stringValue(item.delta ?? item.change);
  const note = stringValue(item.description ?? item.note);

  return (
    <article className="ob-dashboard-kpi">
      <div className="ob-dashboard-kpi__label">{label}</div>
      <div className="ob-dashboard-kpi__value">
        {value}
        {unit && <span>{unit}</span>}
      </div>
      {delta && <div className="ob-dashboard-kpi__delta">{delta}</div>}
      {note && <div className="ob-dashboard-kpi__note">{note}</div>}
    </article>
  );
}

function ChartPanel({
  panel,
  index,
  parentId,
  datasets,
  surface,
}: {
  panel: DashboardRecord;
  index: number;
  parentId: string;
  datasets: DashboardDatasets;
  surface: A2UISurface;
}) {
  const data = resolvePanelData(panel, datasets);
  const chartJs = chartJsRecords(panel.data);
  const title = stringValue(panel.title, "Chart");
  const description = stringValue(panel.description);
  const xKey =
    axisField(
      panel,
      ["x_field", "xField", "x", "x_key", "xKey", "x_axis", "xAxis", "label_column", "labelColumn"],
      ["x", "label_column", "labelColumn"],
    ) ||
    (chartJs.rows.length > 0 ? chartJs.xKey : "") ||
    firstCategoryKey(data);
  const yAxisKey =
    axisField(
      panel,
      [
        "y_field",
        "yField",
        "y",
        "y_key",
        "yKey",
        "y_axis",
        "yAxis",
        "value_field",
        "valueField",
        "value_column",
        "valueColumn",
      ],
      ["y", "value_column", "valueColumn"],
    ) ||
    (Array.isArray(panel.y_fields) ? fieldFromAxis(panel.y_fields[0]) : "") ||
    (Array.isArray(panel.yFields) ? fieldFromAxis(panel.yFields[0]) : "") ||
    (chartJs.rows.length > 0 ? chartJs.yKey : "");
  const seriesValue = panel.series ?? (yAxisKey || panel.metric || panel.value);
  const series = stringList(seriesValue);
  const yKeys = series.length > 0 ? series : [firstNumericKey(data, xKey)];
  const height = Number(panel.height) || 280;
  const options = {
    ...(isRecord(panel.options) ? panel.options : {}),
    xKey,
    series: yKeys,
  };
  const chartComponent: A2UIComponent = {
    id: `${parentId}-chart-${index}`,
    component: "ObChart",
    title,
    chartType: chartType(panel),
    data,
    options,
    height,
  };

  return (
    <article className="ob-dashboard-panel ob-dashboard-panel--chart">
      {description && <p className="ob-dashboard-panel__description">{description}</p>}
      <ObChart component={chartComponent} surface={surface} />
    </article>
  );
}

function TablePanel({
  panel,
  index,
  parentId,
  datasets,
  surface,
}: {
  panel: DashboardRecord;
  index: number;
  parentId: string;
  datasets: DashboardDatasets;
  surface: A2UISurface;
}) {
  const data = resolvePanelData(panel, datasets);
  const columns = normalizeTableColumns(panel.columns, data);
  const headers = columns.map((column) => column.header);
  const rows = data
    .slice(0, maxRows(panel))
    .map((row) => columns.map((column) => formatDashboardValue(tableCellValue(row, column))));
  const title = stringValue(panel.title, "Table");
  const description = stringValue(panel.description);
  const tableComponent: A2UIComponent = {
    id: `${parentId}-table-${index}`,
    component: "ObTable",
    headers,
    rows,
    striped: true,
    compact: true,
  };

  return (
    <article className="ob-dashboard-panel ob-dashboard-panel--table">
      <div className="ob-dashboard-panel__header">
        <h3>{title}</h3>
        {description && <p className="ob-dashboard-panel__description">{description}</p>}
      </div>
      <ObTable component={tableComponent} surface={surface} />
    </article>
  );
}

function TextPanel({ panel }: { panel: DashboardRecord }) {
  const title = stringValue(panel.title, "Summary");
  const rawContent = panel.content ?? panel.text ?? panel.value;
  const content =
    typeof rawContent === "string" ||
    typeof rawContent === "number" ||
    typeof rawContent === "boolean"
      ? stringValue(rawContent)
      : "";

  return (
    <article className="ob-dashboard-panel ob-dashboard-panel--text">
      <h3>{title}</h3>
      {content && <p>{content}</p>}
    </article>
  );
}

function DashboardPanel({
  panel,
  index,
  parentId,
  datasets,
  surface,
}: {
  panel: DashboardRecord;
  index: number;
  parentId: string;
  datasets: DashboardDatasets;
  surface: A2UISurface;
}) {
  const kind = panelKind(panel);
  if (["chart", "bar", "line", "area", "pie", "scatter"].includes(kind)) {
    return (
      <ChartPanel
        panel={panel}
        index={index}
        parentId={parentId}
        datasets={datasets}
        surface={surface}
      />
    );
  }
  if (kind === "table") {
    return (
      <TablePanel
        panel={panel}
        index={index}
        parentId={parentId}
        datasets={datasets}
        surface={surface}
      />
    );
  }
  return <TextPanel panel={panel} />;
}

function DashboardSection({
  section,
  sectionIndex,
  parentId,
  datasets,
  surface,
}: {
  section: DashboardRecord;
  sectionIndex: number;
  parentId: string;
  datasets: DashboardDatasets;
  surface: A2UISurface;
}) {
  const title = stringValue(section.title, `Section ${sectionIndex + 1}`);
  const description = stringValue(section.description);
  const items = panelItems(section);

  if (items.length === 0) return null;

  return (
    <section className="ob-dashboard-section">
      <div className="ob-dashboard-section__heading">
        <h3>{title}</h3>
        {description && <p>{description}</p>}
      </div>
      <div className="ob-dashboard-panel-grid">
        {items.map((panel, index) => (
          <DashboardPanel
            key={stableKey(panel, `${title}-panel`)}
            panel={panel}
            index={index}
            parentId={`${parentId}-section-${sectionIndex}`}
            datasets={datasets}
            surface={surface}
          />
        ))}
      </div>
    </section>
  );
}

export const ObDashboardFrame: A2UIComponentRenderer = ({ component, surface }) => {
  const dashboardComponent = normalizeComponentProperties(component);
  const rawViewModel = resolveValue(
    dashboardComponent.viewModel ?? dashboardComponent.view_model,
    surface,
  );
  const viewModel = parseViewModel(rawViewModel);
  const rawComponents = [
    ...toRows(resolveValue(viewModel?.components ?? dashboardComponent.components, surface)),
    ...toRows(viewModel?.charts),
  ];
  const componentLayout = componentsToLayout(rawComponents);
  const componentKpis = componentLayout.kpis;
  const componentPanels = componentLayout.panels;
  const componentSections = [
    ...componentLayout.sections,
    ...(componentPanels.length > 0 ? [{ title: "Dashboard", items: componentPanels }] : []),
  ];
  const rawDatasets =
    viewModel?.datasets !== undefined
      ? viewModel.datasets
      : resolveValue(dashboardComponent.datasets, surface);
  const rawKpis =
    viewModel?.kpis !== undefined ? viewModel.kpis : resolveValue(dashboardComponent.kpis, surface);
  const rawSections =
    viewModel?.sections !== undefined
      ? viewModel.sections
      : resolveValue(dashboardComponent.sections, surface);
  const rawItems =
    viewModel?.items ??
    viewModel?.panels ??
    viewModel?.charts ??
    viewModel?.widgets ??
    (componentPanels.length > 0 ? componentPanels : undefined) ??
    resolveValue(
      dashboardComponent.items ??
        dashboardComponent.panels ??
        dashboardComponent.charts ??
        dashboardComponent.widgets,
      surface,
    );

  const datasets = normalizeDatasets(rawDatasets);
  const normalizedKpis = toRows(rawKpis);
  const kpis = normalizedKpis.length > 0 ? normalizedKpis : componentKpis;
  const rawSectionsHaveItems = toRows(rawSections).some(
    (section) => panelItems(section).length > 0,
  );
  const normalizedSections =
    componentSections.length > 0 &&
    (!rawSectionsHaveItems ||
      sectionsContainComponentContainers(rawSections) ||
      sectionsHaveOnlyEmptyCharts(rawSections))
      ? componentSections
      : sectionsFrom(rawSections, rawItems);
  const datasetFallbackPanels =
    normalizedSections.length === 0 && shouldSynthesizePanelsFromDatasets(datasets)
      ? panelsFromDatasets(datasets)
      : [];
  const sections =
    normalizedSections.length > 0
      ? normalizedSections
      : datasetFallbackPanels.length > 0
        ? [{ title: "Dashboard", items: datasetFallbackPanels }]
        : [];
  const hasDashboardData =
    Boolean(viewModel) ||
    kpis.length > 0 ||
    sections.length > 0 ||
    Object.keys(datasets).length > 0;

  const title = resolveString(dashboardComponent.title ?? viewModel?.title ?? "Dashboard", surface);
  const description = resolveString(
    dashboardComponent.description ?? viewModel?.description ?? dashboardComponent.summary ?? "",
    surface,
  );
  const dashboardUrl = resolveString(
    dashboardComponent.dashboardUrl ?? dashboardComponent.url ?? "",
    surface,
  );
  const fileName = resolveString(dashboardComponent.fileName ?? "dashboard.html", surface);
  const summary = dashboardComponent.summary
    ? resolveString(dashboardComponent.summary, surface)
    : "";
  const height =
    dashboardComponent.height != null ? resolveNumber(dashboardComponent.height, surface) : 420;
  const fileSize =
    dashboardComponent.fileSize != null
      ? resolveNumber(dashboardComponent.fileSize, surface)
      : undefined;
  const preview = dashboardComponent.preview !== false;
  const templateFormat = templateFormatFrom(dashboardComponent);
  const templateSource = templateSourceFrom(dashboardComponent, templateFormat);
  const exportViewModel = viewModel ?? { title, description, datasets, kpis, sections };

  if (dashboardUrl) {
    return (
      <section
        className="ob-dashboard-frame"
        data-component-id={dashboardComponent.id}
        data-dashboard-renderer="html-export"
        data-dashboard-template-source={templateSource}
        data-dashboard-template-format={templateFormat || "default"}
      >
        <NativeHeader
          title={title}
          description={description || summary}
          dashboardUrl={dashboardUrl}
          fileName={fileName}
          fileSize={fileSize}
          viewModel={hasDashboardData ? exportViewModel : undefined}
        />
        {preview && dashboardUrl && (
          <HtmlFallbackPreview url={dashboardUrl} title={title} height={height} />
        )}
      </section>
    );
  }

  if (!hasDashboardData) {
    return (
      <section
        className="ob-dashboard-frame ob-dashboard-frame--native"
        data-component-id={dashboardComponent.id}
        data-dashboard-renderer="empty"
        data-dashboard-template-source={templateSource}
        data-dashboard-template-format={templateFormat || "default"}
      >
        <NativeHeader
          title={title}
          description={description || summary}
          dashboardUrl=""
          fileName={fileName}
          fileSize={fileSize}
        />
        <div className="ob-dashboard-frame__empty">No dashboard data.</div>
      </section>
    );
  }

  return (
    <section
      className="ob-dashboard-frame ob-dashboard-frame--native"
      data-component-id={dashboardComponent.id}
      data-dashboard-renderer="a2ui"
      data-dashboard-template-source={templateSource}
      data-dashboard-template-format={templateFormat || "default"}
    >
      <NativeHeader
        title={title}
        description={description}
        dashboardUrl={dashboardUrl}
        fileName={fileName}
        fileSize={fileSize}
        viewModel={exportViewModel}
      />
      {kpis.length > 0 && (
        <div className="ob-dashboard-kpi-grid">
          {kpis.map((item, index) => (
            <KpiCard
              key={stableKey(item, "kpi")}
              item={item}
              index={index}
              datasets={datasets}
            />
          ))}
        </div>
      )}
      {sections.map((section, index) => (
        <DashboardSection
          key={stableKey(section, "section")}
          section={section}
          sectionIndex={index}
          parentId={dashboardComponent.id}
          datasets={datasets}
          surface={surface}
        />
      ))}
      {kpis.length === 0 && sections.length === 0 && (
        <div className="ob-dashboard-frame__empty">No dashboard panels.</div>
      )}
    </section>
  );
};
