/** Public, sign-in-free page for a live dashboard (`/d/<id>`).
 *
 * Loads the current snapshot from `/d/{id}/data`, then follows server
 * pushes on `/d/{id}/events` with the browser's own `EventSource` (no auth
 * header needed: the backend only serves dashboards flagged public and
 * never includes queries or owner). Renders through the same
 * `ObDashboardFrame` the chat uses, via a synthetic A2UI surface. */
import { SurfaceRenderer, type A2UISurface } from "@openbench/chat-ui";
import { useEffect, useMemo, useState } from "react";
import { apiPath } from "../api";
import { LIVE_DASHBOARD } from "../i18n/id";

export type PublicDashboardPayload = {
  id: string;
  title: string;
  description?: string;
  viewModel: unknown;
  version: number;
  refreshedAt?: string | null;
  refreshIntervalSeconds?: number;
  errors?: Record<string, string>;
  lastError?: string | null;
};

type Connection = "connecting" | "live" | "offline" | "closed";

/** Reconnect when no event (the server pings every 15 s) arrived for this long. */
const SILENCE_MS = 45_000;
const WATCHDOG_TICK_MS = 5_000;

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; payload: PublicDashboardPayload; connection: Connection };

function formatClock(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function dashboardSurface(payload: PublicDashboardPayload): A2UISurface {
  return {
    surfaceId: `public-${payload.id}`,
    catalogId: "openbench",
    components: new Map([
      [
        "root",
        {
          id: "root",
          component: "ObDashboardFrame",
          properties: {
            title: payload.title,
            description: payload.description ?? "",
            viewModel: payload.viewModel,
          },
        },
      ],
    ]),
    dataModel: {},
  };
}

export function PublicDashboardPage({ dashboardId }: { dashboardId: string }) {
  const [state, setState] = useState<PageState>({ status: "loading" });

  useEffect(() => {
    document.body.classList.add("public-dashboard-root");
    return () => document.body.classList.remove("public-dashboard-root");
  }, []);

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let closed = false;
    let lastEventAt = Date.now();
    let watchdog: ReturnType<typeof setInterval> | null = null;

    const applyPayload = (payload: PublicDashboardPayload, connection: Connection) => {
      if (cancelled) return;
      document.title = payload.title;
      setState({ status: "ready", payload, connection });
    };

    const markOffline = () =>
      setState((current) =>
        current.status === "ready" && current.connection !== "closed"
          ? { ...current, connection: "offline" }
          : current,
      );

    const connect = () => {
      if (cancelled || closed || typeof EventSource === "undefined") return;
      source?.close();
      lastEventAt = Date.now();
      source = new EventSource(apiPath(`/d/${encodeURIComponent(dashboardId)}/events`));
      const touch = () => {
        lastEventAt = Date.now();
      };
      const onData = (event: MessageEvent<string>) => {
        touch();
        try {
          applyPayload(JSON.parse(event.data) as PublicDashboardPayload, "live");
        } catch {
          // Ignore malformed frames; the next push replaces the view.
        }
      };
      source.addEventListener("snapshot", onData as EventListener);
      source.addEventListener("update", onData as EventListener);
      source.addEventListener("ping", touch as EventListener);
      source.addEventListener("error", touch as EventListener);
      source.addEventListener("closed", (() => {
        closed = true;
        source?.close();
        setState((current) =>
          current.status === "ready" ? { ...current, connection: "closed" } : current,
        );
      }) as EventListener);
      source.onopen = () => {
        touch();
        setState((current) =>
          current.status === "ready" ? { ...current, connection: "live" } : current,
        );
      };
      source.onerror = () => {
        // A server-sent `event: error` (refresh failure) also lands here
        // while the connection is healthy; only a real transport gap counts.
        if (source?.readyState === EventSource.OPEN) return;
        // EventSource reconnects by itself; reflect the gap in the badge.
        markOffline();
      };
    };

    void (async () => {
      try {
        const response = await fetch(apiPath(`/d/${encodeURIComponent(dashboardId)}/data`));
        if (response.status === 404) throw new Error("not-found");
        if (!response.ok) throw new Error(String(response.status));
        const payload = (await response.json()) as PublicDashboardPayload;
        applyPayload(payload, "connecting");
      } catch (error) {
        if (cancelled) return;
        const notFound = error instanceof Error && error.message === "not-found";
        setState({
          status: "error",
          message: notFound ? LIVE_DASHBOARD.notFound : LIVE_DASHBOARD.loadFailed,
        });
        return;
      }
      if (cancelled) return;
      connect();
      // A proxy can keep our side open after the upstream died; EventSource
      // then never reconnects on its own. No ping for SILENCE_MS -> rebuild it.
      watchdog = setInterval(() => {
        if (closed || !source) return;
        if (Date.now() - lastEventAt > SILENCE_MS) {
          markOffline();
          connect();
        }
      }, WATCHDOG_TICK_MS);
    })();

    return () => {
      cancelled = true;
      if (watchdog) clearInterval(watchdog);
      source?.close();
    };
  }, [dashboardId]);

  const surface = useMemo(
    () => (state.status === "ready" ? dashboardSurface(state.payload) : null),
    [state],
  );

  if (state.status === "loading") {
    return <div className="public-dashboard__notice">{LIVE_DASHBOARD.loading}</div>;
  }
  if (state.status === "error") {
    return (
      <div className="public-dashboard__notice" role="alert">
        {state.message}
      </div>
    );
  }

  const { payload, connection } = state;
  const clock = formatClock(payload.refreshedAt);
  const badgeText =
    connection === "closed"
      ? LIVE_DASHBOARD.unavailable
      : connection === "offline"
        ? LIVE_DASHBOARD.offline
        : connection === "connecting"
          ? LIVE_DASHBOARD.connecting
          : clock
            ? `${LIVE_DASHBOARD.live} · ${LIVE_DASHBOARD.updated} ${clock}`
            : LIVE_DASHBOARD.live;

  return (
    <main className="public-dashboard">
      <header className="public-dashboard__header">
        <div className="public-dashboard__title-wrap">
          <h1 className="public-dashboard__title">{payload.title}</h1>
          {payload.description && (
            <p className="public-dashboard__description">{payload.description}</p>
          )}
        </div>
        <div className="public-dashboard__live" data-live-state={connection} role="status">
          <span className="public-dashboard__live-dot" aria-hidden="true" />
          {badgeText}
        </div>
      </header>
      {surface && (
        <div className="public-dashboard__surface">
          <SurfaceRenderer surface={surface} />
        </div>
      )}
    </main>
  );
}
