/**
 * Tests for AGUITransport (AG-UI protocol).
 *
 * Mocks HttpAgent for SSE event streams and fetch for REST actions.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { AGUITransport } from "../src/core/transport";
import type { ChatConfig } from "../src/types";

// ── Mock HttpAgent ──

// We mock @ag-ui/client to avoid real HTTP requests and rxjs dependency in tests
vi.mock("@ag-ui/client", () => {
  return {
    HttpAgent: vi.fn(),
  };
});

import { HttpAgent } from "@ag-ui/client";

function createMockAgent(events: Record<string, unknown>[]) {
  const MockedHttpAgent = HttpAgent as unknown as ReturnType<typeof vi.fn>;
  MockedHttpAgent.mockImplementation(() => ({
    run: () => ({
      subscribe: (observer: {
        next: (e: Record<string, unknown>) => void;
        error: (e: Error) => void;
        complete: () => void;
      }) => {
        for (const event of events) {
          observer.next(event);
        }
        observer.complete();
        return { unsubscribe: vi.fn() };
      },
    }),
  }));
}

function createMockAgentError(error: Error) {
  const MockedHttpAgent = HttpAgent as unknown as ReturnType<typeof vi.fn>;
  MockedHttpAgent.mockImplementation(() => ({
    run: () => ({
      subscribe: (observer: {
        next: (e: Record<string, unknown>) => void;
        error: (e: Error) => void;
        complete: () => void;
      }) => {
        observer.error(error);
        return { unsubscribe: vi.fn() };
      },
    }),
  }));
}

function createJSONResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const config: ChatConfig = {
  streamUrl: "/awp",
};

// ── AG-UI Event Streaming ──

describe("AGUITransport events", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts as disconnected", () => {
    createMockAgent([]);
    const t = new AGUITransport(config);
    expect(t.status).toBe("disconnected");
    t.dispose();
  });

  it("run() dispatches AG-UI events to listeners", async () => {
    const events = [
      { type: "RUN_STARTED", threadId: "t1", runId: "r1" },
      { type: "STEP_STARTED", stepName: "Processing input" },
      { type: "STEP_FINISHED", stepName: "Processing input" },
      {
        type: "CUSTOM",
        name: "a2ui",
        value: { version: "v0.10", createSurface: { surfaceId: "s-1" } },
      },
      { type: "RUN_FINISHED", threadId: "t1", runId: "r1", result: { content: "Hello" } },
    ];

    createMockAgent(events);

    const t = new AGUITransport(config);
    const listener = vi.fn();
    t.onEvent(listener);

    await t.run("Hello");

    expect(listener).toHaveBeenCalledTimes(5);
    expect(listener).toHaveBeenNthCalledWith(1, events[0]);
    expect(listener).toHaveBeenNthCalledWith(2, events[1]);
    expect(listener).toHaveBeenNthCalledWith(5, events[4]);

    t.dispose();
  });

  it("run() sets status to connected on event", async () => {
    createMockAgent([{ type: "RUN_STARTED", threadId: "t1", runId: "r1" }]);

    const t = new AGUITransport(config);
    const statusListener = vi.fn();
    t.onStatusChange(statusListener);

    await t.run("Hello");

    expect(t.status).toBe("connected");
    expect(statusListener).toHaveBeenCalledWith("connected");

    t.dispose();
  });

  it("run() sets status to error on failure", async () => {
    createMockAgentError(new Error("Network error"));

    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const t = new AGUITransport(config);
    const statusListener = vi.fn();
    t.onStatusChange(statusListener);

    await expect(t.run("Hello")).rejects.toThrow("Network error");

    expect(t.status).toBe("error");
    expect(statusListener).toHaveBeenCalledWith("error");

    errSpy.mockRestore();
    t.dispose();
  });

  it("run() creates HttpAgent with correct URL", async () => {
    createMockAgent([]);

    const t = new AGUITransport(config);
    await t.run("Hello");

    expect(HttpAgent).toHaveBeenCalledWith({ url: "/awp" });

    t.dispose();
  });

  it("cancel() unsubscribes from active stream", async () => {
    const unsubMock = vi.fn();
    const MockedHttpAgent = HttpAgent as unknown as ReturnType<typeof vi.fn>;
    MockedHttpAgent.mockImplementation(() => ({
      run: () => ({
        subscribe: () => {
          // Never complete — simulates long-running stream
          return { unsubscribe: unsubMock };
        },
      }),
    }));

    const t = new AGUITransport(config);

    // Start stream (don't await — it would hang)
    const _runPromise = t.run("Hello");

    // Cancel immediately
    t.cancel();

    expect(unsubMock).toHaveBeenCalled();

    t.dispose();
  });
});

// ── REST Actions ──

describe("AGUITransport REST actions", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sendAction() dispatches response as CUSTOM events", async () => {
    createMockAgent([]);
    const responseMessages = [
      { version: "v0.10", createSurface: { surfaceId: "s-1" } },
      { version: "v0.10", updateComponents: { surfaceId: "s-1", components: [] } },
    ];

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createJSONResponse(responseMessages)));

    const t = new AGUITransport(config);
    const listener = vi.fn();
    t.onEvent(listener);

    await t.sendAction({
      name: "submit",
      surfaceId: "surface-1",
      sourceComponentId: "btn-1",
      timestamp: new Date().toISOString(),
      context: { value: "test" },
    });

    expect(listener).toHaveBeenCalledTimes(2);
    // Each response message should be wrapped as CUSTOM event
    expect(listener.mock.calls[0][0]).toEqual({
      type: "CUSTOM",
      name: "a2ui",
      value: responseMessages[0],
    });

    t.dispose();
  });

  it("sendAction() posts to default /chat/action URL", async () => {
    createMockAgent([]);
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const t = new AGUITransport(config);

    await t.sendAction({
      name: "click",
      surfaceId: "s1",
      sourceComponentId: "btn-1",
      timestamp: "2026-01-01T00:00:00Z",
      context: {},
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/action",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    );

    t.dispose();
  });

  it("sendAction() uses custom actionUrl when configured", async () => {
    createMockAgent([]);
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const t = new AGUITransport({ streamUrl: "/awp", actionUrl: "/api/action" });

    await t.sendAction({
      name: "click",
      surfaceId: "s1",
      sourceComponentId: "btn-1",
      timestamp: "2026-01-01T00:00:00Z",
      context: {},
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/action",
      expect.objectContaining({ method: "POST" }),
    );

    t.dispose();
  });

  it("sendAction() sets status to error on failure", async () => {
    createMockAgent([]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const t = new AGUITransport(config);
    await t.sendAction({
      name: "click",
      surfaceId: "s1",
      sourceComponentId: "btn-1",
      timestamp: "2026-01-01T00:00:00Z",
      context: {},
    });

    expect(t.status).toBe("error");

    errSpy.mockRestore();
    t.dispose();
  });
});

// ── File Upload ──

describe("AGUITransport upload", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("upload() sends file as multipart/form-data", async () => {
    createMockAgent([]);
    const serverResponse = {
      id: "file-abc123",
      type: "file",
      name: "report.pdf",
      url: "/uploads/file-abc123/report.pdf",
      mimeType: "application/pdf",
      sizeBytes: 1024,
    };

    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse(serverResponse));
    vi.stubGlobal("fetch", fetchMock);

    const t = new AGUITransport(config);
    const file = new File(["test content"], "report.pdf", { type: "application/pdf" });

    const result = await t.upload(file);

    expect(result.id).toBe("file-abc123");
    expect(result.name).toBe("report.pdf");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/chat/upload");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);

    t.dispose();
  });

  it("upload() throws on server error", async () => {
    createMockAgent([]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    const t = new AGUITransport(config);
    const file = new File(["data"], "f.txt", { type: "text/plain" });

    await expect(t.upload(file)).rejects.toThrow("Upload failed: 500");

    t.dispose();
  });
});

// ── Listeners ──

describe("AGUITransport listeners", () => {
  it("unsubscribes event listener", async () => {
    createMockAgent([{ type: "RUN_STARTED", threadId: "t1", runId: "r1" }]);

    const t = new AGUITransport(config);
    const listener = vi.fn();
    const unsub = t.onEvent(listener);

    await t.run("Hello");
    expect(listener).toHaveBeenCalledTimes(1);

    unsub();

    createMockAgent([{ type: "RUN_STARTED", threadId: "t2", runId: "r2" }]);

    await t.run("World");
    expect(listener).toHaveBeenCalledTimes(1); // Not called again

    t.dispose();
  });

  it("unsubscribes status listener", async () => {
    createMockAgent([]);

    const t = new AGUITransport(config);
    const listener = vi.fn();
    const unsub = t.onStatusChange(listener);

    unsub();

    await t.run("Hello");
    expect(listener).not.toHaveBeenCalled();

    t.dispose();
  });
});

// ── Dispose ──

describe("AGUITransport dispose", () => {
  it("clears all listeners and sets disconnected", async () => {
    createMockAgent([{ type: "RUN_STARTED", threadId: "t1", runId: "r1" }]);

    const t = new AGUITransport(config);
    const eventListener = vi.fn();
    const statusListener = vi.fn();

    t.onEvent(eventListener);
    t.onStatusChange(statusListener);

    await t.run("Hello");

    eventListener.mockClear();
    statusListener.mockClear();

    t.dispose();

    expect(t.status).toBe("disconnected");
    expect(statusListener).toHaveBeenCalledTimes(1);
    expect(statusListener).toHaveBeenCalledWith("disconnected");
  });
});
