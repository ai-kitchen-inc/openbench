import type { LiveDashboardEvent } from "@openbench/chat-ui";
import {
  createLiveSubscriptionPool,
  parseSseBuffer,
  subscribeDashboardEvents,
  toLiveEvent,
} from "./liveDashboard";

function streamResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

async function flush(): Promise<void> {
  for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("parseSseBuffer", () => {
  it("splits complete frames and keeps the unterminated tail", () => {
    const text = ': ping\n\nevent: snapshot\ndata: {"a":1}\n\nevent: update\ndata: {"b":\ndata: 2}\n\nevent: upd';
    const { frames, rest } = parseSseBuffer(text);
    expect(frames).toEqual([
      { event: "snapshot", data: '{"a":1}' },
      { event: "update", data: '{"b":\n2}' },
    ]);
    expect(rest).toBe("event: upd");
  });

  it("maps frames onto SDK events", () => {
    expect(
      toLiveEvent({ event: "update", data: JSON.stringify({ version: 3, viewModel: { x: 1 }, refreshedAt: "t" }) }),
    ).toEqual({ type: "update", version: 3, viewModel: { x: 1 }, refreshedAt: "t", errors: undefined });
    expect(toLiveEvent({ event: "closed", data: '{"reason":"deleted"}' })).toEqual({
      type: "closed",
      reason: "deleted",
    });
    expect(toLiveEvent({ event: "error", data: '{"error":"boom"}' })).toMatchObject({ type: "error", error: "boom" });
    expect(toLiveEvent({ event: "noise", data: "{}" })).toBeNull();
    expect(toLiveEvent({ event: "update", data: "not json" })).toBeNull();
  });
});

describe("subscribeDashboardEvents", () => {
  it("sends the bearer token in a header and delivers parsed events", async () => {
    const calls: RequestInit[] = [];
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      calls.push(init ?? {});
      return streamResponse([
        'event: snapshot\ndata: {"version":1,"viewModel":{"k":1}}\n\n',
        'event: closed\ndata: {"reason":"deleted"}\n\n',
      ]);
    }) as unknown as typeof fetch;
    const events: LiveDashboardEvent[] = [];
    subscribeDashboardEvents(
      "/dashboard/live/abc/events",
      {
        getAuthToken: async () => "tok-1",
        extraHeaders: () => ({ "X-Local-Role": "user" }),
        fetchImpl,
      },
      (event) => events.push(event),
    );
    await flush();
    const headers = calls[0].headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok-1");
    expect(headers["X-Local-Role"]).toBe("user");
    expect(headers.Accept).toBe("text/event-stream");
    expect(events.map((event) => event.type)).toEqual(["status", "snapshot", "closed"]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("stops on 404 without reconnecting", async () => {
    const fetchImpl = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const events: LiveDashboardEvent[] = [];
    subscribeDashboardEvents(
      "/d/abc/events",
      { getAuthToken: async () => null, fetchImpl, minDelayMs: 1 },
      (event) => events.push(event),
    );
    await flush();
    expect(events[events.length - 1]).toEqual({ type: "closed", reason: "http-404" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("reconnects after a dropped stream and stops when unsubscribed", async () => {
    let attempts = 0;
    const fetchImpl = vi.fn(async () => {
      attempts += 1;
      return streamResponse([]);
    }) as unknown as typeof fetch;
    const events: LiveDashboardEvent[] = [];
    const stop = subscribeDashboardEvents(
      "/dashboard/live/abc/events",
      { getAuthToken: async () => "t", fetchImpl, minDelayMs: 1, maxDelayMs: 2 },
      (event) => events.push(event),
    );
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(attempts).toBeGreaterThan(1);
    expect(events.some((event) => event.type === "status" && event.status === "offline")).toBe(true);
    stop();
    const after = attempts;
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(attempts).toBe(after);
  });
});

describe("createLiveSubscriptionPool", () => {
  it("shares one upstream per id and replays the last snapshot to late joiners", () => {
    const handlers = new Map<string, (event: LiveDashboardEvent) => void>();
    const unsubscribe = vi.fn();
    const upstream = vi.fn((id: string, onEvent: (event: LiveDashboardEvent) => void) => {
      handlers.set(id, onEvent);
      return unsubscribe;
    });
    const pool = createLiveSubscriptionPool(upstream);
    const first: LiveDashboardEvent[] = [];
    const second: LiveDashboardEvent[] = [];
    const stopFirst = pool("d1", (event) => first.push(event));
    handlers.get("d1")?.({ type: "snapshot", version: 1, viewModel: {} });
    const stopSecond = pool("d1", (event) => second.push(event));
    expect(upstream).toHaveBeenCalledTimes(1);
    expect(second).toHaveLength(1);
    expect(second[0].type).toBe("snapshot");
    stopFirst();
    expect(unsubscribe).not.toHaveBeenCalled();
    stopSecond();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
    pool("d1", () => {});
    expect(upstream).toHaveBeenCalledTimes(2);
  });
});
