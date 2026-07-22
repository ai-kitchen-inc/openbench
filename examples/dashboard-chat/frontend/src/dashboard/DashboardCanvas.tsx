import { LayoutDashboard, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { getDashboard, type DashboardSpec, type PanelSpec } from "../api";
import { ChartPanel } from "./ChartPanel";
import { KpiCard } from "./KpiCard";
import { PanelErrorBoundary } from "./PanelFrame";
import { TablePanel } from "./TablePanel";

const WIDTH_SPAN: Record<string, number> = {
  third: 2,
  half: 3,
  twothirds: 4,
  full: 6,
};

function Panel({ panel, reloadToken }: { panel: PanelSpec; reloadToken: number }) {
  if (panel.type === "kpi") return <KpiCard panel={panel} reloadToken={reloadToken} />;
  if (panel.type === "table") return <TablePanel panel={panel} reloadToken={reloadToken} />;
  return <ChartPanel panel={panel} reloadToken={reloadToken} />;
}

/** The main dashboard surface. `refreshTick` (chat turn finished) refetches
 * the spec — panels re-query only if their SQL changed. `dataTick` (manual
 * refresh) additionally forces every panel to re-run its query. */
export function DashboardCanvas({
  refreshTick,
  dataTick,
  assistantBusy = false,
}: {
  refreshTick: number;
  dataTick: number;
  assistantBusy?: boolean;
}) {
  const [spec, setSpec] = useState<DashboardSpec | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDashboard()
      .then((loaded) => {
        if (cancelled) return;
        setError(null);
        setIsLoading(false);
        // Keep the object identity stable when nothing changed so panels
        // don't refetch their data on every chat turn.
        setSpec((current) =>
          loaded === null || current?.version === loaded.version ? current ?? loaded : loaded,
        );
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setIsLoading(false);
        setError(err instanceof Error ? err.message : "Could not load the dashboard.");
      });
    return () => {
      cancelled = true;
    };
  }, [refreshTick, dataTick]);

  if (isLoading) {
    return (
      <div className="canvas-empty">
        <Loader2 size={20} strokeWidth={1.5} className="spin" />
      </div>
    );
  }

  if (error) {
    return <div className="canvas-empty">{error}</div>;
  }

  if (spec === null) {
    if (assistantBusy) {
      return (
        <div className="canvas-empty">
          <Loader2 size={24} strokeWidth={1.5} className="spin" />
          <h2>Building your dashboard</h2>
          <p>
            The assistant is analyzing your schema, writing the queries, and laying out the
            panels. This usually takes a moment.
          </p>
        </div>
      );
    }
    return (
      <div className="canvas-empty">
        <LayoutDashboard size={28} strokeWidth={1.25} />
        <h2>No dashboard yet</h2>
        <p>Ask the assistant for one in the chat — it will appear here.</p>
      </div>
    );
  }

  return (
    <div className="canvas">
      <header className="canvas__header">
        <h1 className="canvas__title">{spec.title}</h1>
        {spec.description && <p className="canvas__description">{spec.description}</p>}
      </header>
      <div className="canvas__grid">
        {spec.panels.map((panel) => (
          <div
            key={panel.id}
            className="canvas__cell"
            style={{ gridColumn: `span ${WIDTH_SPAN[panel.width ?? "half"] ?? 3}` }}
          >
            <PanelErrorBoundary title={panel.title}>
              <Panel panel={panel} reloadToken={dataTick} />
            </PanelErrorBoundary>
          </div>
        ))}
      </div>
    </div>
  );
}
