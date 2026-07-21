import { useEffect, useState } from "react";
import { getPanelData, type PanelData } from "../api";

export interface PanelDataState {
  data: PanelData | null;
  error: string | null;
  isLoading: boolean;
  reload: () => void;
}

/** Fetch a panel's rows; re-runs when the panel's SQL (spec version) changes
 * or when `reloadToken` bumps (manual refresh — same SQL, fresh data). */
export function usePanelData(panelId: string, sql: string, reloadToken = 0): PanelDataState {
  const [data, setData] = useState<PanelData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setError(null);
    getPanelData(panelId, controller.signal)
      .then((result) => {
        setData(result);
        setIsLoading(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Query failed.");
        setData(null);
        setIsLoading(false);
      });
    return () => controller.abort();
    // `sql` is part of the key: a panel whose query changed must refetch
    // even though its id stayed the same.
  }, [panelId, sql, attempt, reloadToken]);

  return { data, error, isLoading, reload: () => setAttempt((n) => n + 1) };
}
