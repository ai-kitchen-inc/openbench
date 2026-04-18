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


/** Installs a fake ``XMLHttpRequest`` on ``globalThis`` that resolves
 *  to the given status/body. Returns an inspection handle so tests can
 *  assert on headers, open() args, and the request body.
 */
interface MockXHRHandle {
  openCalls: [string, string, boolean][];
  headers: Map<string, string>;
  lastBody: unknown;
}

function installMockXHR(response: { status: number; responseText: string }): MockXHRHandle {
  const handle: MockXHRHandle = {
    openCalls: [],
    headers: new Map(),
    lastBody: null,
  };
  class FakeXHR {
    upload = { onprogress: null as ((ev: ProgressEvent) => void) | null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    status = 0;
    responseText = "";
    open(method: string, url: string, async: boolean) {
      handle.openCalls.push([method, url, async]);
    }
    setRequestHeader(k: string, v: string) {
      handle.headers.set(k, v);
    }
    send(body: unknown) {
      handle.lastBody = body;
      // Resolve on next microtask so the caller can attach listeners.
      queueMicrotask(() => {
        this.status = response.status;
        this.responseText = response.responseText;
        this.onload?.();
      });
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXHR as unknown as typeof XMLHttpRequest);
  return handle;
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

    expect(HttpAgent).toHaveBeenCalledWith(expect.objectContaining({ url: "/awp" }));

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

    // Start stream (don't await the long-running run — it would hang).
    // We DO await a microtask so the transport's internal getAuthToken()
    // promise resolves and subscribe() runs before we cancel.
    const _runPromise = t.run("Hello");
    await Promise.resolve();
    await Promise.resolve();

    // Cancel
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

  it("sendAction() includes dataModel and threadId when provided", async () => {
    createMockAgent([]);
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const t = new AGUITransport(config);

    await t.sendAction({
      name: "submit",
      surfaceId: "s1",
      sourceComponentId: "btn-1",
      timestamp: "2026-01-01T00:00:00Z",
      context: { value: "test" },
      dataModel: { form: { name: "Alice" } },
      threadId: "session-123",
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.dataModel).toEqual({ form: { name: "Alice" } });
    expect(body.threadId).toBe("session-123");

    t.dispose();
  });

  it("sendAction() throws and sets status to error on failure", async () => {
    createMockAgent([]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const t = new AGUITransport(config);
    await expect(
      t.sendAction({
        name: "click",
        surfaceId: "s1",
        sourceComponentId: "btn-1",
        timestamp: "2026-01-01T00:00:00Z",
        context: {},
      }),
    ).rejects.toThrow("Action request failed: 500");

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

    const xhr = installMockXHR({ status: 200, responseText: JSON.stringify(serverResponse) });
    const t = new AGUITransport(config);
    const file = new File(["test content"], "report.pdf", { type: "application/pdf" });

    const result = await t.upload(file);

    expect(result.id).toBe("file-abc123");
    expect(result.name).toBe("report.pdf");
    expect(xhr.openCalls).toEqual([["POST", "/chat/upload", true]]);
    expect(xhr.lastBody).toBeInstanceOf(FormData);

    t.dispose();
  });

  it("upload() fires onProgress callback with normalized fractions", async () => {
    createMockAgent([]);
    // A custom XHR fake so we can drive the progress events explicitly.
    const progressFns: ((ev: ProgressEvent) => void)[] = [];
    let resolveLoad: (() => void) | null = null;
    class ProgressXHR {
      upload = {
        set onprogress(fn: (ev: ProgressEvent) => void) {
          progressFns.push(fn);
        },
      };
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      status = 0;
      responseText = "";
      open() {}
      setRequestHeader() {}
      send() {
        resolveLoad = () => {
          this.status = 200;
          this.responseText = JSON.stringify({
            id: "a",
            type: "file",
            name: "f",
            url: "/u/f",
            mimeType: "text/plain",
          });
          this.onload?.();
        };
      }
    }
    vi.stubGlobal("XMLHttpRequest", ProgressXHR as unknown as typeof XMLHttpRequest);

    const seen: number[] = [];
    const t = new AGUITransport(config);
    const promise = t.upload(new File(["x"], "f.txt", { type: "text/plain" }), {
      onProgress: (frac) => seen.push(frac),
    });
    // Fire two progress events + completion.
    await Promise.resolve();
    const fn = progressFns[0];
    fn({ lengthComputable: true, loaded: 50, total: 200 } as ProgressEvent);
    fn({ lengthComputable: true, loaded: 120, total: 200 } as ProgressEvent);
    // Non-computable should be ignored.
    fn({ lengthComputable: false, loaded: 999, total: 0 } as ProgressEvent);
    resolveLoad?.();
    await promise;

    // Two real events + the explicit 1.0 at completion.
    expect(seen).toEqual([0.25, 0.6, 1]);
  });

  it("upload() throws on server error", async () => {
    createMockAgent([]);
    installMockXHR({ status: 500, responseText: "" });
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

// ── Sessions REST ──

describe("AGUITransport sessions", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("listSessions returns parsed summaries", async () => {
    const summaries = [
      {
        sessionId: "s-1",
        title: "Q1 review",
        createdAt: "2026-04-17T10:00:00Z",
        updatedAt: "2026-04-17T10:00:00Z",
        messageCount: 4,
        preview: "tell me about q1",
      },
    ];
    global.fetch = vi.fn().mockResolvedValue(createJSONResponse(summaries));
    const t = new AGUITransport(config);
    const result = await t.listSessions(10, 0);
    expect(result).toEqual(summaries);
    expect(global.fetch).toHaveBeenCalledWith(
      "/sessions?limit=10&offset=0",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("listSessions returns empty array on 501", async () => {
    global.fetch = vi.fn().mockResolvedValue(createJSONResponse({}, 501));
    const t = new AGUITransport(config);
    expect(await t.listSessions()).toEqual([]);
  });

  it("listSessions returns empty array on fetch error", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));
    const t = new AGUITransport(config);
    expect(await t.listSessions()).toEqual([]);
  });

  it("listSessions uses custom sessionsUrl", async () => {
    global.fetch = vi.fn().mockResolvedValue(createJSONResponse([]));
    const t = new AGUITransport({ ...config, sessionsUrl: "/api/v2/sessions" });
    await t.listSessions(5, 2);
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v2/sessions?limit=5&offset=2",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("loadSession returns a ChatSession with normalized fields", async () => {
    const wire = {
      sessionId: "s-42",
      title: "Saved",
      createdAt: "2026-04-17T10:00:00Z",
      updatedAt: "2026-04-17T10:05:00Z",
      messages: [
        {
          id: "m-1",
          role: "user",
          content: "hello",
          timestamp: "2026-04-17T10:00:00Z",
        },
        {
          id: "m-2",
          role: "assistant",
          content: "hi back",
          timestamp: "2026-04-17T10:00:30Z",
        },
      ],
    };
    global.fetch = vi.fn().mockResolvedValue(createJSONResponse(wire));
    const t = new AGUITransport(config);
    const session = await t.loadSession("s-42");
    expect(session).not.toBeNull();
    expect(session?.id).toBe("s-42");
    expect(session?.messages).toHaveLength(2);
    expect(session?.messages[0].status).toBe("complete");
  });

  it("loadSession returns null on 404", async () => {
    global.fetch = vi.fn().mockResolvedValue(createJSONResponse({}, 404));
    const t = new AGUITransport(config);
    expect(await t.loadSession("missing")).toBeNull();
  });

  it("deleteSession issues DELETE request", async () => {
    global.fetch = vi.fn().mockResolvedValue(createJSONResponse({}, 200));
    const t = new AGUITransport(config);
    await t.deleteSession("s-1");
    expect(global.fetch).toHaveBeenCalledWith(
      "/sessions/s-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("deleteSession swallows 404", async () => {
    global.fetch = vi.fn().mockResolvedValue(createJSONResponse({}, 404));
    const t = new AGUITransport(config);
    await expect(t.deleteSession("missing")).resolves.toBeUndefined();
  });

  it("deleteSession encodes session id", async () => {
    global.fetch = vi.fn().mockResolvedValue(createJSONResponse({}, 200));
    const t = new AGUITransport(config);
    await t.deleteSession("id with/slash");
    expect(global.fetch).toHaveBeenCalledWith(
      "/sessions/id%20with%2Fslash",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("deleteSession throws on 500", async () => {
    global.fetch = vi.fn().mockResolvedValue(createJSONResponse({}, 500));
    const t = new AGUITransport(config);
    await expect(t.deleteSession("x")).rejects.toThrow();
  });
});

// ── Authorization header (Firebase ID token) ──

describe("AGUITransport Authorization header", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("listSessions attaches Bearer token when getAuthToken is wired", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    global.fetch = fetchMock;
    const t = new AGUITransport({
      ...config,
      getAuthToken: async () => "fake-id-token",
    });
    await t.listSessions();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({ Authorization: "Bearer fake-id-token" }),
      }),
    );
  });

  it("loadSession attaches Bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createJSONResponse({
        sessionId: "s-1",
        title: "t",
        createdAt: "2026-04-18T00:00:00Z",
        updatedAt: "2026-04-18T00:00:00Z",
        messages: [],
      }),
    );
    global.fetch = fetchMock;
    const t = new AGUITransport({
      ...config,
      getAuthToken: async () => "tok-1",
    });
    await t.loadSession("s-1");
    const call = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = call.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok-1");
  });

  it("deleteSession attaches Bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse({}, 200));
    global.fetch = fetchMock;
    const t = new AGUITransport({
      ...config,
      getAuthToken: async () => "tok-del",
    });
    await t.deleteSession("s-1");
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok-del");
  });

  it("sendAction attaches Bearer token alongside Content-Type", async () => {
    createMockAgent([]);
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const t = new AGUITransport({
      ...config,
      getAuthToken: async () => "tok-act",
    });
    await t.sendAction({
      name: "click",
      surfaceId: "s1",
      sourceComponentId: "btn-1",
      timestamp: "2026-04-18T00:00:00Z",
      context: {},
    });
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok-act");
    expect(headers["Content-Type"]).toBe("application/json");
    t.dispose();
  });

  it("upload attaches Bearer token without setting Content-Type", async () => {
    const xhr = installMockXHR({
      status: 200,
      responseText: JSON.stringify({
        id: "att-1",
        type: "file",
        name: "x",
        url: "/u/x",
        mimeType: "text/plain",
      }),
    });
    const t = new AGUITransport({
      ...config,
      getAuthToken: async () => "tok-up",
    });
    await t.upload(new File(["hello"], "hello.txt", { type: "text/plain" }));
    // XHR's setRequestHeader calls — pluck what upload() set.
    const headers = Object.fromEntries(xhr.headers);
    expect(headers.Authorization).toBe("Bearer tok-up");
    // Content-Type must NOT be set manually — XHR infers multipart/form-data
    // with boundary when the body is FormData.
    expect(headers["Content-Type"]).toBeUndefined();
  });

  it("run passes Bearer token into HttpAgent headers", async () => {
    createMockAgent([]);
    const t = new AGUITransport({
      ...config,
      getAuthToken: async () => "tok-sse",
    });
    await t.run("hi");
    expect(HttpAgent).toHaveBeenCalledWith(
      expect.objectContaining({
        url: "/awp",
        headers: expect.objectContaining({ Authorization: "Bearer tok-sse" }),
      }),
    );
    t.dispose();
  });

  it("no header attached when getAuthToken is unset", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    global.fetch = fetchMock;
    const t = new AGUITransport(config); // no getAuthToken
    await t.listSessions();
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers?.Authorization).toBeUndefined();
  });

  it("no header attached when getAuthToken returns null", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    global.fetch = fetchMock;
    const t = new AGUITransport({ ...config, getAuthToken: async () => null });
    await t.listSessions();
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers?.Authorization).toBeUndefined();
  });

  it("getAuthToken error is swallowed — request still runs without auth", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    global.fetch = fetchMock;
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const t = new AGUITransport({
      ...config,
      getAuthToken: async () => {
        throw new Error("token fetch failed");
      },
    });
    const result = await t.listSessions();
    expect(result).toEqual([]);
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers?.Authorization).toBeUndefined();
    errSpy.mockRestore();
  });
});

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
