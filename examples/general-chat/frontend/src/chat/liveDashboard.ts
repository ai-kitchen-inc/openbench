/** Live dashboard transport for the SSS frontend.
 *
 * The authenticated stream (`/dashboard/live/{id}/events`) needs the
 * Firebase bearer token, which the browser's `EventSource` cannot send, so
 * this module parses server-sent events from a plain `fetch` body instead.
 * Tokens never go into the URL. A per-tab pool makes the inline message
 * frame and the side panel share one connection per dashboard. */
import type { LiveDashboardEvent } from "@openbench/chat-ui";

export type SseFrame = { event: string; data: string };

/** Split a buffer of SSE text into complete frames; `rest` is the unterminated tail. */
export function parseSseBuffer(buffer: string): { frames: SseFrame[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const frames: SseFrame[] = [];
  let start = 0;
  for (;;) {
    const end = normalized.indexOf("\n\n", start);
    if (end === -1) break;
    const block = normalized.slice(start, end);
    start = end + 2;
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length > 0) frames.push({ event, data: data.join("\n") });
  }
  return { frames, rest: normalized.slice(start) };
}

/** Map a raw frame onto the SDK's `LiveDashboardEvent`; unknown frames are dropped. */
export function toLiveEvent(frame: SseFrame): LiveDashboardEvent | null {
  let payload: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(frame.data);
    if (typeof parsed !== "object" || parsed === null) return null;
    payload = parsed as Record<string, unknown>;
  } catch {
    return null;
  }
  switch (frame.event) {
    case "snapshot":
    case "update":
      return {
        type: frame.event,
        version: typeof payload.version === "number" ? payload.version : 0,
        viewModel: payload.viewModel,
        refreshedAt: typeof payload.refreshedAt === "string" ? payload.refreshedAt : null,
        errors:
          typeof payload.errors === "object" && payload.errors !== null
            ? (payload.errors as Record<string, string>)
            : undefined,
      };
    case "error":
      return {
        type: "error",
        error: typeof payload.error === "string" ? payload.error : "Pembaruan gagal",
        refreshedAt: typeof payload.refreshedAt === "string" ? payload.refreshedAt : null,
      };
    case "closed":
      return {
        type: "closed",
        reason: typeof payload.reason === "string" ? payload.reason : "closed",
      };
    default:
      return null;
  }
}

export type SubscribeOptions = {
  getAuthToken: () => Promise<string | null>;
  /** Extra request headers (e.g. the local-dev role override). */
  extraHeaders?: () => Record<string, string>;
  fetchImpl?: typeof fetch;
  /** Reconnect backoff bounds (ms). */
  minDelayMs?: number;
  maxDelayMs?: number;
  /** Reconnect when nothing (not even a heartbeat) arrived for this long. */
  silenceMs?: number;
};

/** HTTP statuses that mean "stop, do not reconnect". */
const TERMINAL_STATUSES = new Set([401, 403, 404, 410]);

/**
 * Open a fetch-based SSE subscription with exponential reconnect.
 * Returns a function that stops the stream and any pending reconnect.
 */
export function subscribeDashboardEvents(
  url: string,
  options: SubscribeOptions,
  onEvent: (event: LiveDashboardEvent) => void,
): () => void {
  const fetchImpl = options.fetchImpl ?? fetch;
  const minDelay = options.minDelayMs ?? 1000;
  const maxDelay = options.maxDelayMs ?? 30_000;
  // The server pings every 15 s; a silently dropped socket would otherwise
  // keep the badge on "live" with stale data forever.
  const silenceMs = options.silenceMs ?? 45_000;
  let stopped = false;
  let delay = minDelay;
  let controller: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const emit = (event: LiveDashboardEvent) => {
    if (!stopped) onEvent(event);
  };

  async function connect(): Promise<void> {
    if (stopped) return;
    emit({ type: "status", status: "connecting" });
    controller = new AbortController();
    try {
      const headers: Record<string, string> = {
        Accept: "text/event-stream",
        ...(options.extraHeaders?.() ?? {}),
      };
      const token = await options.getAuthToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const response = await fetchImpl(url, { headers, signal: controller.signal });
      if (TERMINAL_STATUSES.has(response.status)) {
        emit({ type: "closed", reason: `http-${response.status}` });
        stopped = true;
        return;
      }
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let lastChunkAt = Date.now();
      const activeController = controller;
      const watchdog = setInterval(
        () => {
          if (Date.now() - lastChunkAt > silenceMs) activeController.abort();
        },
        Math.min(5000, silenceMs),
      );
      try {
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          lastChunkAt = Date.now();
          delay = minDelay; // reset backoff only once data actually flows
          buffer += decoder.decode(value, { stream: true });
          const parsed = parseSseBuffer(buffer);
          buffer = parsed.rest;
          for (const frame of parsed.frames) {
            const event = toLiveEvent(frame);
            if (!event) continue;
            emit(event);
            if (event.type === "closed") {
              stopped = true;
              controller.abort();
              return;
            }
          }
        }
      } finally {
        clearInterval(watchdog);
      }
    } catch {
      // Network error or abort: fall through to the reconnect below.
    }
    if (stopped) return;
    emit({ type: "status", status: "offline" });
    timer = setTimeout(() => {
      timer = null;
      void connect();
    }, delay);
    delay = Math.min(maxDelay, delay * 2);
  }

  void connect();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    controller?.abort();
  };
}

type Listener = (event: LiveDashboardEvent) => void;
type Subscribe = (dashboardId: string, onEvent: Listener) => () => void;

/**
 * Reference-counted fan-out: one upstream subscription per dashboard id,
 * shared by every frame that renders it in this tab. Late joiners receive
 * the last snapshot/update immediately.
 */
export function createLiveSubscriptionPool(subscribe: Subscribe): Subscribe {
  const entries = new Map<
    string,
    { listeners: Set<Listener>; unsubscribe: () => void; last: LiveDashboardEvent | null }
  >();
  return (dashboardId, onEvent) => {
    let entry = entries.get(dashboardId);
    if (!entry) {
      const created = {
        listeners: new Set<Listener>(),
        unsubscribe: () => {},
        last: null as LiveDashboardEvent | null,
      };
      entries.set(dashboardId, created);
      created.unsubscribe = subscribe(dashboardId, (event) => {
        if (event.type === "snapshot" || event.type === "update" || event.type === "closed") {
          created.last = event;
        }
        for (const listener of created.listeners) listener(event);
      });
      entry = created;
    }
    entry.listeners.add(onEvent);
    if (entry.last) onEvent(entry.last);
    return () => {
      const current = entries.get(dashboardId);
      if (!current) return;
      current.listeners.delete(onEvent);
      if (current.listeners.size === 0) {
        current.unsubscribe();
        entries.delete(dashboardId);
      }
    };
  };
}
