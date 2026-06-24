/**
 * ObDashboardFrame - OpenBench native dashboard renderer.
 */

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

function firstKey(records: DashboardRecord[]): string {
  return records[0] ? (Object.keys(records[0])[0] ?? "name") : "name";
}

function firstNumericKey(records: DashboardRecord[], fallback: string): string {
  const row = records[0];
  if (!row) return fallback;
  return (
    Object.keys(row).find((key) => key !== fallback && typeof row[key] === "number") ?? fallback
  );
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

function NativeHeader({
  title,
  description,
  dashboardUrl,
  fileName,
  fileSize,
}: {
  title: string;
  description: string;
  dashboardUrl: string;
  fileName: string;
  fileSize?: number;
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
      {dashboardUrl && (
        <a
          className="ob-dashboard-frame__open"
          href={dashboardUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          <ExternalLinkIcon />
          Open
        </a>
      )}
    </header>
  );
}

function KpiCard({ item, index }: { item: DashboardRecord; index: number }) {
  const label = stringValue(item.label ?? item.title, `KPI ${index + 1}`);
  const value = formatDashboardValue(item.value);
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
    firstKey(data),
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
          <iframe
            title={title}
            src={dashboardUrl}
            className="ob-dashboard-frame__iframe"
            style={{ height: `${Math.max(260, Math.min(height, 720))}px` }}
          />
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
      />
      {kpis.length > 0 && (
        <div className="ob-dashboard-kpi-grid">
          {kpis.map((item, index) => (
            <KpiCard key={stableKey(item, "kpi")} item={item} index={index} />
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
