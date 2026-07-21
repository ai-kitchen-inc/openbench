import type { PanelSpec } from "../api";
import { usePanelData } from "./usePanelData";
import { PanelFrame } from "./PanelFrame";

function formatValue(
  value: string | number | boolean | null,
  format: PanelSpec["format"],
  unit?: string,
): string {
  if (value === null || value === undefined) return "—";
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(numeric)) return String(value);
  if (format === "currency") {
    const formatted = new Intl.NumberFormat(undefined, {
      maximumFractionDigits: numeric >= 1000 ? 0 : 2,
    }).format(numeric);
    return unit ? `${unit} ${formatted}` : formatted;
  }
  if (format === "percent") {
    return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(numeric)}%`;
  }
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: Number.isInteger(numeric) ? 0 : 2,
  }).format(numeric);
}

/** Stat tile: a single hero number. Expects a 1-row, 1-value query. */
export function KpiCard({ panel }: { panel: PanelSpec }) {
  const { data, error, isLoading, reload } = usePanelData(panel.id, panel.sql);
  const value = data?.rows?.[0]?.[data.columns.length - 1] ?? null;

  return (
    <PanelFrame title={panel.title} isLoading={isLoading} error={error} onRetry={reload}>
      <div className="kpi">
        <span className="kpi__value">{formatValue(value, panel.format, panel.unit)}</span>
      </div>
    </PanelFrame>
  );
}
