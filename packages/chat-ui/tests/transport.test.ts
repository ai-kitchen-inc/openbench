/**
 * Tests for ChatTransport (SSE + REST).
 *
 * Mocks fetch for both SSE streams and REST actions.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatTransport } from "../src/core/transport";
import type { ChatConfig } from "../src/types";

// ── Helpers ──

function createSSEResponse(events: Record<string, unknown>[]): Response {
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function createJSONResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const config: ChatConfig = {
  streamUrl: "/chat/stream",
};

// ── SSE Streaming ──

describe("ChatTransport SSE", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts as disconnected", () => {
    const t = new ChatTransport(config);
    expect(t.status).toBe("disconnected");
    t.dispose();
  });

  it("stream() dispatches SSE events to listeners", async () => {
    const events = [
      { type: "stream_start", messageId: "msg-1" },
      { type: "step_start", stepId: "s1", stepName: "Thinking" },
      { type: "step_complete", stepId: "s1" },
      { type: "stream_end", messageId: "msg-1" },
    ];

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createSSEResponse(events)));

    const t = new ChatTransport(config);
    const listener = vi.fn();
    t.onMessage(listener);

    await t.stream({ type: "message", content: "Hello" });

    expect(listener).toHaveBeenCalledTimes(4);
    expect(listener).toHaveBeenNthCalledWith(1, { type: "stream_start", messageId: "msg-1" });
    expect(listener).toHaveBeenNthCalledWith(2, {
      type: "step_start",
      stepId: "s1",
      stepName: "Thinking",
    });
    expect(listener).toHaveBeenNthCalledWith(3, { type: "step_complete", stepId: "s1" });
    expect(listener).toHaveBeenNthCalledWith(4, { type: "stream_end", messageId: "msg-1" });

    t.dispose();
  });

  it("stream() sends correct POST request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createSSEResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const t = new ChatTransport(config);

    await t.stream({
      type: "message",
      content: "Test",
      sessionId: "sess-1",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/stream",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "message", content: "Test", sessionId: "sess-1" }),
      }),
    );

    t.dispose();
  });

  it("stream() sets status to connected on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createSSEResponse([])));

    const t = new ChatTransport(config);
    const statusListener = vi.fn();
    t.onStatusChange(statusListener);

    await t.stream({ type: "message", content: "Hello" });

    expect(t.status).toBe("connected");
    expect(statusListener).toHaveBeenCalledWith("connected");

    t.dispose();
  });

  it("stream() sets status to error on failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const t = new ChatTransport(config);
    const statusListener = vi.fn();
    t.onStatusChange(statusListener);

    await t.stream({ type: "message", content: "Hello" });

    expect(t.status).toBe("error");
    expect(statusListener).toHaveBeenCalledWith("error");

    errSpy.mockRestore();
    t.dispose();
  });

  it("stream() handles network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));

    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const t = new ChatTransport(config);
    await t.stream({ type: "message", content: "Hello" });

    expect(t.status).toBe("error");

    errSpy.mockRestore();
    t.dispose();
  });

  it("stream() skips malformed JSON in SSE events", async () => {
    const text = 'data: {"valid":true}\n\ndata: not-json{\n\ndata: {"also":"valid"}\n\n';
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(text));
        controller.close();
      },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    const t = new ChatTransport(config);
    const listener = vi.fn();
    t.onMessage(listener);

    await t.stream({ type: "message", content: "Hello" });

    expect(listener).toHaveBeenCalledTimes(2);
    expect(listener).toHaveBeenNthCalledWith(1, { valid: true });
    expect(listener).toHaveBeenNthCalledWith(2, { also: "valid" });

    t.dispose();
  });

  it("abort() cancels in-flight stream", async () => {
    // Mock fetch that rejects with AbortError when signal is aborted
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        return new Promise((_resolve, reject) => {
          if (init?.signal) {
            init.signal.addEventListener("abort", () => {
              const err = new Error("The operation was aborted.");
              err.name = "AbortError";
              reject(err);
            });
          }
        });
      }),
    );

    const t = new ChatTransport(config);

    // Start stream (don't await — it would hang without abort)
    const streamPromise = t.stream({ type: "message", content: "Hello" });

    // Abort immediately
    t.abort();

    // Should resolve without error (AbortError is caught internally)
    await streamPromise;

    // Status should NOT be "error" (AbortError is intentional)
    expect(t.status).not.toBe("error");

    t.dispose();
  });
});

// ── REST Actions ──

describe("ChatTransport REST", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sendAction() dispatches response messages to listeners", async () => {
    const responseMessages = [
      { type: "stream_start", messageId: "msg-2" },
      { type: "stream_end", messageId: "msg-2" },
    ];

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createJSONResponse(responseMessages)));

    const t = new ChatTransport(config);
    const listener = vi.fn();
    t.onMessage(listener);

    await t.sendAction({
      type: "action",
      name: "submit",
      surfaceId: "surface-1",
      sourceComponentId: "btn-1",
      timestamp: new Date().toISOString(),
      context: { value: "test" },
    });

    expect(listener).toHaveBeenCalledTimes(2);
    expect(listener).toHaveBeenNthCalledWith(1, { type: "stream_start", messageId: "msg-2" });
    expect(listener).toHaveBeenNthCalledWith(2, { type: "stream_end", messageId: "msg-2" });

    t.dispose();
  });

  it("sendAction() posts to default /chat/action URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const t = new ChatTransport(config);

    await t.sendAction({
      type: "action",
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
    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const t = new ChatTransport({ streamUrl: "/chat/stream", actionUrl: "/api/action" });

    await t.sendAction({
      type: "action",
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

  it("sendAction() sets status to connected on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createJSONResponse([])));

    const t = new ChatTransport(config);
    const statusListener = vi.fn();
    t.onStatusChange(statusListener);

    await t.sendAction({
      type: "action",
      name: "click",
      surfaceId: "s1",
      sourceComponentId: "btn-1",
      timestamp: "2026-01-01T00:00:00Z",
      context: {},
    });

    expect(t.status).toBe("connected");

    t.dispose();
  });

  it("sendAction() sets status to error on failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const t = new ChatTransport(config);
    await t.sendAction({
      type: "action",
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

// ── Listeners ──

describe("ChatTransport listeners", () => {
  it("unsubscribes message listener", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(createSSEResponse([{ type: "stream_start", messageId: "msg-1" }])),
    );

    const t = new ChatTransport(config);
    const listener = vi.fn();
    const unsub = t.onMessage(listener);

    await t.stream({ type: "message", content: "Hello" });
    expect(listener).toHaveBeenCalledTimes(1);

    unsub();

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(createSSEResponse([{ type: "stream_start", messageId: "msg-2" }])),
    );

    await t.stream({ type: "message", content: "World" });
    expect(listener).toHaveBeenCalledTimes(1); // Not called again

    t.dispose();
  });

  it("unsubscribes status listener", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createSSEResponse([])));

    const t = new ChatTransport(config);
    const listener = vi.fn();
    const unsub = t.onStatusChange(listener);

    unsub();

    await t.stream({ type: "message", content: "Hello" });
    expect(listener).not.toHaveBeenCalled();

    t.dispose();
  });
});

// ── File Upload ──

describe("ChatTransport upload", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("upload() sends file as multipart/form-data", async () => {
    const serverResponse = {
      id: "file-abc123",
      type: "file",
      name: "report.pdf",
      url: "/uploads/file-abc123/report.pdf",
      mimeType: "application/pdf",
      sizeBytes: 1024,
      extractedText: "PDF content here",
    };

    const fetchMock = vi.fn().mockResolvedValue(createJSONResponse(serverResponse));
    vi.stubGlobal("fetch", fetchMock);

    const t = new ChatTransport(config);
    const file = new File(["test content"], "report.pdf", { type: "application/pdf" });

    const result = await t.upload(file);

    expect(result.id).toBe("file-abc123");
    expect(result.name).toBe("report.pdf");
    expect(result.url).toBe("/uploads/file-abc123/report.pdf");
    expect(result.mimeType).toBe("application/pdf");

    // Verify fetch was called with FormData
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/chat/upload");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);

    t.dispose();
  });

  it("upload() uses custom uploadUrl when configured", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createJSONResponse({
        id: "f1",
        type: "file",
        name: "f.txt",
        url: "/f",
        mimeType: "text/plain",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const t = new ChatTransport({ streamUrl: "/chat/stream", uploadUrl: "/api/upload" });
    const file = new File(["data"], "f.txt", { type: "text/plain" });
    await t.upload(file);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/upload",
      expect.objectContaining({ method: "POST" }),
    );

    t.dispose();
  });

  it("upload() throws on server error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    const t = new ChatTransport(config);
    const file = new File(["data"], "f.txt", { type: "text/plain" });

    await expect(t.upload(file)).rejects.toThrow("Upload failed: 500");

    t.dispose();
  });
});

// ── Dispose ──

describe("ChatTransport dispose", () => {
  it("clears all listeners and sets disconnected", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createSSEResponse([])));

    const t = new ChatTransport(config);
    const msgListener = vi.fn();
    const statusListener = vi.fn();

    t.onMessage(msgListener);
    t.onStatusChange(statusListener);

    await t.stream({ type: "message", content: "Hello" });

    // Reset mocks to verify no more calls after dispose
    msgListener.mockClear();
    statusListener.mockClear();

    t.dispose();

    expect(t.status).toBe("disconnected");
    // statusListener gets one call for the "disconnected" transition
    expect(statusListener).toHaveBeenCalledTimes(1);
    expect(statusListener).toHaveBeenCalledWith("disconnected");
  });
});
