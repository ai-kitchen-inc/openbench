/**
 * ObDashboardFrame - OpenBench native dashboard renderer.
 */

import { useEffect, useState } from "react";
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
    result[key] = toRows(rows);
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

function resolvePanelData(panel: DashboardRecord, datasets: DashboardDatasets): DashboardRecord[] {
  const directRows = toRows(panel.data ?? panel.records);
  if (directRows.length > 0) return directRows;

  const datasetKey = stringValue(
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
  if (sections.length > 0) return sections;

  const items = toRows(fallbackItems);
  return items.length > 0 ? [{ title: "Dashboard", items }] : [];
}

function panelKind(panel: DashboardRecord): string {
  return stringValue(panel.type ?? panel.kind, "chart").toLowerCase();
}

function chartType(panel: DashboardRecord): string {
  const requested = stringValue(
    panel.chart_type ?? panel.chartType ?? panel.visualization ?? panel.visualizationType ?? panel.type,
    "bar",
  ).toLowerCase();
  return ["bar", "line", "pie", "scatter", "area"].includes(requested) ? requested : "bar";
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

function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function HeaderActions({ viewModel, title }: { viewModel: unknown; title: string }) {
  const actions = useChatContextOptional()?.dashboardActions;
  const [busy, setBusy] = useState<"publish" | "export" | null>(null);
  const [publishedUrl, setPublishedUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!actions || (!actions.publish && !actions.exportGrafana)) return null;

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
        {actions.exportGrafana && (
          <button
            type="button"
            className="ob-dashboard-frame__action"
            onClick={handleExport}
            disabled={busy !== null}
          >
            <DownloadIcon />
            {busy === "export" ? "Exporting…" : "Export"}
          </button>
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
 * Inline preview for the html-fallback path. When ``loadHtml`` is available,
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
  const fmt = stringValue(item.format);
  if (fmt.includes("$") && !text.startsWith("$")) return `$${text}`;
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
  const title = stringValue(panel.title, "Chart");
  const description = stringValue(panel.description);
  const xKey = stringValue(
    panel.x ?? panel.x_key ?? panel.xKey ?? panel.x_axis ?? panel.xAxis ?? panel.xField,
    firstCategoryKey(data),
  );
  const series = stringList(
    panel.series ??
      panel.y ??
      panel.y_key ??
      panel.yKey ??
      panel.y_axis ??
      panel.yAxis ??
      panel.yField ??
      panel.metric ??
      panel.value,
  );
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
  const content = stringValue(panel.content ?? panel.text ?? panel.value);

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
    resolveValue(
      dashboardComponent.items ??
        dashboardComponent.panels ??
        dashboardComponent.charts ??
        dashboardComponent.widgets,
      surface,
    );

  const datasets = normalizeDatasets(rawDatasets);
  const kpis = toRows(rawKpis);
  const sections = sectionsFrom(rawSections, rawItems);
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

  if (!hasDashboardData && dashboardUrl) {
    return (
      <section
        className="ob-dashboard-frame"
        data-component-id={dashboardComponent.id}
        data-dashboard-renderer="html-fallback"
      >
        <NativeHeader
          title={title}
          description={summary}
          dashboardUrl={dashboardUrl}
          fileName={fileName}
          fileSize={fileSize}
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

  // ViewModel to hand to Publish / Export: prefer the parsed one, else
  // reconstruct from the already-normalized props.
  const exportViewModel = viewModel ?? { title, description, datasets, kpis, sections };

  return (
    <section
      className="ob-dashboard-frame ob-dashboard-frame--native"
      data-component-id={dashboardComponent.id}
      data-dashboard-renderer="a2ui"
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
