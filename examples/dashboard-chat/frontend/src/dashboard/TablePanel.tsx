import type { PanelSpec } from "../api";
import { usePanelData } from "./usePanelData";
import { PanelFrame } from "./PanelFrame";

const MAX_TABLE_ROWS = 100;

export function TablePanel({ panel, reloadToken }: { panel: PanelSpec; reloadToken?: number }) {
  const { data, error, isLoading, reload } = usePanelData(panel.id, panel.sql, reloadToken);
  const rows = data?.rows.slice(0, MAX_TABLE_ROWS) ?? [];
  const meta =
    data && data.rows.length > MAX_TABLE_ROWS ? `showing ${MAX_TABLE_ROWS} rows` : undefined;

  return (
    <PanelFrame title={panel.title} isLoading={isLoading} error={error} onRetry={reload} meta={meta}>
      {data && rows.length === 0 ? (
        <div className="panel__empty">No rows.</div>
      ) : (
        data && (
          <div className="panel__table-wrap">
            <table className="panel__table">
              <thead>
                <tr>
                  {data.columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((value, cellIndex) => (
                      <td
                        key={cellIndex}
                        className={typeof value === "number" ? "panel__table-num" : undefined}
                      >
                        {value === null ? "—" : String(value)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </PanelFrame>
  );
}
