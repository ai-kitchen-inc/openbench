/**
 * useLiveDashboard - subscribe an ObDashboardFrame to server pushes.
 *
 * The transport is host-provided through `dashboardActions.subscribeLive`
 * (see `DashboardActions`), so the SDK stays backend-agnostic. Without a
 * subscription function the hook is inert and the frame keeps rendering the
 * ViewModel baked into the A2UI message.
 */

import { useCallback, useEffect, useState } from "react";
import { useChatContextOptional } from "../../components/ChatProvider";
import type { LiveDashboardEvent, LiveDashboardLabels } from "../../types";

export type LiveDashboardState = "idle" | "connecting" | "live" | "offline" | "unavailable";

export interface LiveDashboardStatus {
  state: LiveDashboardState;
  /** ISO timestamp of the snapshot currently displayed. */
  updatedAt: string | null;
  version: number | null;
  /** Latest refresh problem (whole refresh failed or one dataset errored). */
  error: string | null;
  busy: boolean;
  /** Present when the host wired `refreshLive`. */
  onRefresh?: () => void;
}

export const DEFAULT_LIVE_LABELS: LiveDashboardLabels = {
  live: "Live",
  connecting: "Connecting…",
  offline: "Reconnecting…",
  unavailable: "Dashboard no longer available",
  updated: "updated",
  refresh: "Refresh data",
};

function firstError(errors: Record<string, string> | undefined): string | null {
  if (!errors) return null;
  const first = Object.entries(errors)[0];
  if (!first) return null;
  return `${first[0]}: ${first[1]}`;
}

export function useLiveDashboard(
  dashboardId: string | undefined,
  enabled: boolean,
): LiveDashboardStatus & { viewModel: unknown } {
  const actions = useChatContextOptional()?.dashboardActions;
  const subscribe = actions?.subscribeLive;
  const refreshLive = actions?.refreshLive;
  const active = enabled && Boolean(dashboardId) && Boolean(subscribe);

  const [viewModel, setViewModel] = useState<unknown>(undefined);
  const [version, setVersion] = useState<number | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [state, setState] = useState<LiveDashboardState>(active ? "connecting" : "idle");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!active || !dashboardId || !subscribe) {
      setState("idle");
      return;
    }
    setState("connecting");
    const unsubscribe = subscribe(dashboardId, (event: LiveDashboardEvent) => {
      switch (event.type) {
        case "snapshot":
        case "update":
          setViewModel(event.viewModel);
          setVersion(event.version);
          setUpdatedAt(event.refreshedAt ?? new Date().toISOString());
          setError(firstError(event.errors));
          setState("live");
          break;
        case "error":
          setError(event.error);
          setState("live");
          break;
        case "closed":
          setState("unavailable");
          break;
        case "status":
          setState(event.status);
          break;
        default:
          break;
      }
    });
    return () => {
      unsubscribe();
    };
  }, [active, dashboardId, subscribe]);

  const onRefresh = useCallback(() => {
    if (!refreshLive || !dashboardId || busy) return;
    setBusy(true);
    refreshLive(dashboardId)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setBusy(false));
  }, [busy, dashboardId, refreshLive]);

  return {
    viewModel,
    version,
    updatedAt,
    state,
    error,
    busy,
    onRefresh: refreshLive && dashboardId ? onRefresh : undefined,
  };
}

/** HH:MM for the badge; empty when the timestamp is unparseable. */
export function formatClock(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
