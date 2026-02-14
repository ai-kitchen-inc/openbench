/**
 * Tests for ChatTransport.
 *
 * Uses a mock WebSocket since tests run in jsdom.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatTransport } from "../src/core/transport";
import type { ChatConfig } from "../src/types";

// ── WebSocket Mock ──

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  sentMessages: string[] = [];
  url: string;

  constructor(url: string) {
    this.url = url;
    // Simulate async connection
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.();
    }, 0);
  }

  send(data: string): void {
    this.sentMessages.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }

  // Test helpers
  simulateMessage(data: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  simulateClose(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }

  simulateError(): void {
    this.onerror?.();
  }
}

// Store mock instances for test access
let mockWsInstances: MockWebSocket[] = [];

function installMockWebSocket() {
  mockWsInstances = [];
  (globalThis as Record<string, unknown>).WebSocket = class extends MockWebSocket {
    constructor(url: string) {
      super(url);
      mockWsInstances.push(this);
    }
  };
  // Also set static constants on the class
  (globalThis as Record<string, unknown>).WebSocket = Object.assign(
    (globalThis as Record<string, unknown>).WebSocket as object,
    {
      CONNECTING: 0,
      OPEN: 1,
      CLOSING: 2,
      CLOSED: 3,
    },
  );
}

describe("ChatTransport", () => {
  let transport: ChatTransport;
  const config: ChatConfig = {
    wsUrl: "ws://localhost:8000/chat/ws",
    reconnect: false, // disable reconnect for most tests
  };

  beforeEach(() => {
    vi.useFakeTimers();
    installMockWebSocket();
    transport = new ChatTransport(config);
  });

  afterEach(() => {
    transport.dispose();
    vi.useRealTimers();
  });

  // ── Connection ──

  describe("connection", () => {
    it("starts as disconnected", () => {
      expect(transport.status).toBe("disconnected");
    });

    it("sets status to connecting on connect()", () => {
      transport.connect();
      expect(transport.status).toBe("connecting");
    });

    it("sets status to connected after WebSocket opens", async () => {
      const statusListener = vi.fn();
      transport.onStatusChange(statusListener);

      transport.connect();
      await vi.runAllTimersAsync();

      expect(transport.status).toBe("connected");
      expect(statusListener).toHaveBeenCalledWith("connecting");
      expect(statusListener).toHaveBeenCalledWith("connected");
    });

    it("does not reconnect when already connected", async () => {
      transport.connect();
      await vi.runAllTimersAsync();

      transport.connect(); // should be a no-op
      expect(mockWsInstances).toHaveLength(1);
    });
  });

  // ── Disconnection ──

  describe("disconnection", () => {
    it("sets status to disconnected on disconnect()", async () => {
      transport.connect();
      await vi.runAllTimersAsync();

      transport.disconnect();
      expect(transport.status).toBe("disconnected");
    });

    it("cleans up WebSocket on disconnect", async () => {
      transport.connect();
      await vi.runAllTimersAsync();

      transport.disconnect();
      // No reconnect should be attempted
      await vi.advanceTimersByTimeAsync(5000);
      expect(mockWsInstances).toHaveLength(1);
    });
  });

  // ── Sending ──

  describe("sending", () => {
    it("sends JSON payload when connected", async () => {
      transport.connect();
      await vi.runAllTimersAsync();

      transport.send({
        type: "message",
        content: "Hello",
      });

      const ws = mockWsInstances[0]!;
      expect(ws.sentMessages).toHaveLength(1);
      expect(JSON.parse(ws.sentMessages[0]!)).toEqual({
        type: "message",
        content: "Hello",
      });
    });

    it("warns when sending while disconnected", () => {
      const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

      transport.send({ type: "message", content: "Hello" });

      expect(warn).toHaveBeenCalledWith(expect.stringContaining("not connected"));
      warn.mockRestore();
    });
  });

  // ── Receiving ──

  describe("receiving", () => {
    it("dispatches parsed messages to listeners", async () => {
      const listener = vi.fn();
      transport.onMessage(listener);

      transport.connect();
      await vi.runAllTimersAsync();

      const ws = mockWsInstances[0]!;
      ws.simulateMessage({ type: "stream_start", messageId: "msg-1" });

      expect(listener).toHaveBeenCalledWith({
        type: "stream_start",
        messageId: "msg-1",
      });
    });

    it("handles invalid JSON gracefully", async () => {
      const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const listener = vi.fn();
      transport.onMessage(listener);

      transport.connect();
      await vi.runAllTimersAsync();

      const ws = mockWsInstances[0]!;
      ws.onmessage?.({ data: "not-json{" });

      expect(listener).not.toHaveBeenCalled();
      expect(errorSpy).toHaveBeenCalled();
      errorSpy.mockRestore();
    });

    it("unsubscribes message listener", async () => {
      const listener = vi.fn();
      const unsub = transport.onMessage(listener);

      transport.connect();
      await vi.runAllTimersAsync();

      const ws = mockWsInstances[0]!;
      ws.simulateMessage({ test: 1 });
      expect(listener).toHaveBeenCalledTimes(1);

      unsub();
      ws.simulateMessage({ test: 2 });
      expect(listener).toHaveBeenCalledTimes(1);
    });
  });

  // ── Status listeners ──

  describe("status listeners", () => {
    it("notifies status listeners on change", async () => {
      const listener = vi.fn();
      transport.onStatusChange(listener);

      transport.connect();
      expect(listener).toHaveBeenCalledWith("connecting");

      await vi.runAllTimersAsync();
      expect(listener).toHaveBeenCalledWith("connected");
    });

    it("unsubscribes status listener", () => {
      const listener = vi.fn();
      const unsub = transport.onStatusChange(listener);

      unsub();
      transport.connect();
      expect(listener).not.toHaveBeenCalled();
    });
  });

  // ── Error handling ──

  describe("error handling", () => {
    it("sets error status on WebSocket error", async () => {
      transport.connect();
      await vi.runAllTimersAsync();

      const ws = mockWsInstances[0]!;
      ws.simulateError();

      expect(transport.status).toBe("error");
    });
  });

  // ── Reconnect ──

  describe("reconnect", () => {
    it("attempts reconnect on close", async () => {
      const reconnectConfig: ChatConfig = {
        wsUrl: "ws://localhost:8000/chat/ws",
        reconnect: true,
        reconnectInterval: 1000,
        maxReconnectAttempts: 3,
      };

      transport.dispose();
      transport = new ChatTransport(reconnectConfig);

      transport.connect();
      await vi.runAllTimersAsync();
      expect(mockWsInstances).toHaveLength(1);

      // Simulate close
      const ws = mockWsInstances[0]!;
      ws.simulateClose();

      // Wait for reconnect interval
      await vi.advanceTimersByTimeAsync(1000);
      expect(mockWsInstances.length).toBeGreaterThanOrEqual(2);
    });

    it("stops reconnecting after max attempts", async () => {
      const reconnectConfig: ChatConfig = {
        wsUrl: "ws://localhost:8000/chat/ws",
        reconnect: true,
        reconnectInterval: 100,
        maxReconnectAttempts: 2,
      };

      transport.dispose();

      // Use a mock that does NOT auto-open (simulates persistent connection failure)
      (globalThis as Record<string, unknown>).WebSocket = Object.assign(
        class FailingWebSocket {
          static CONNECTING = 0;
          static OPEN = 1;
          static CLOSING = 2;
          static CLOSED = 3;

          readyState = 0; // CONNECTING, never transitions to OPEN
          onopen: (() => void) | null = null;
          onmessage: ((event: { data: string }) => void) | null = null;
          onclose: (() => void) | null = null;
          onerror: (() => void) | null = null;

          constructor() {
            mockWsInstances.push(this as unknown as MockWebSocket);
            // Simulate connection failure: fire close after a tick
            setTimeout(() => {
              this.readyState = 3; // CLOSED
              this.onclose?.();
            }, 10);
          }

          send(): void {}
          close(): void {
            this.readyState = 3;
          }
        },
        { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 },
      );

      transport = new ChatTransport(reconnectConfig);
      const instancesBefore = mockWsInstances.length;
      transport.connect();

      // Let initial connection fail + all reconnect timers play out
      // Each attempt: 10ms to fail + 100ms reconnect interval
      for (let i = 0; i < 5; i++) {
        await vi.advanceTimersByTimeAsync(150);
      }

      // Should have attempted: 1 initial + 2 reconnects = 3 total
      const newInstances = mockWsInstances.length - instancesBefore;
      expect(newInstances).toBe(3); // initial + 2 retries
      expect(transport.status).toBe("error");
    });

    it("does not reconnect when reconnect is false", async () => {
      transport.connect();
      await vi.runAllTimersAsync();
      expect(mockWsInstances).toHaveLength(1);

      const ws = mockWsInstances[0]!;
      ws.simulateClose();

      await vi.advanceTimersByTimeAsync(5000);
      expect(mockWsInstances).toHaveLength(1); // no new instances
    });
  });

  // ── Dispose ──

  describe("dispose", () => {
    it("clears all listeners and disconnects", async () => {
      const msgListener = vi.fn();
      const statusListener = vi.fn();

      transport.onMessage(msgListener);
      transport.onStatusChange(statusListener);

      transport.connect();
      await vi.runAllTimersAsync();

      transport.dispose();

      expect(transport.status).toBe("disconnected");
      // After dispose, listeners should not fire (cleared)
    });
  });
});

// ── SSE Streaming Tests ──

describe("ChatTransport SSE", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

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

  it("hasSSE returns true when streamUrl is configured", () => {
    const t = new ChatTransport({
      wsUrl: "ws://localhost:8000/chat/ws",
      streamUrl: "/chat/stream",
    });
    expect(t.hasSSE).toBe(true);
    t.dispose();
  });

  it("hasSSE returns false without streamUrl", () => {
    const t = new ChatTransport({
      wsUrl: "ws://localhost:8000/chat/ws",
    });
    expect(t.hasSSE).toBe(false);
    t.dispose();
  });

  it("streamViaSSE dispatches SSE events to listeners", async () => {
    const events = [
      { type: "stream_start", messageId: "msg-1" },
      { type: "step_start", stepId: "s1", stepName: "Thinking" },
      { type: "step_complete", stepId: "s1" },
      { type: "stream_end", messageId: "msg-1" },
    ];

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createSSEResponse(events)));

    const t = new ChatTransport({
      wsUrl: "ws://localhost:8000/chat/ws",
      streamUrl: "/chat/stream",
    });

    const listener = vi.fn();
    t.onMessage(listener);

    await t.streamViaSSE({ type: "message", content: "Hello" });

    expect(listener).toHaveBeenCalledTimes(4);
    expect(listener).toHaveBeenNthCalledWith(1, { type: "stream_start", messageId: "msg-1" });
    expect(listener).toHaveBeenNthCalledWith(2, {
      type: "step_start",
      stepId: "s1",
      stepName: "Thinking",
    });
    expect(listener).toHaveBeenNthCalledWith(4, { type: "stream_end", messageId: "msg-1" });

    t.dispose();
  });

  it("streamViaSSE sends correct POST request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createSSEResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const t = new ChatTransport({
      wsUrl: "ws://localhost:8000/chat/ws",
      streamUrl: "/chat/stream",
    });

    await t.streamViaSSE({
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

  it("streamViaSSE falls back to WebSocket when no streamUrl", async () => {
    installMockWebSocket();

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const t = new ChatTransport({
      wsUrl: "ws://localhost:8000/chat/ws",
      // no streamUrl
    });

    // Connect first so WS send works
    t.connect();
    await new Promise((r) => setTimeout(r, 10));

    await t.streamViaSSE({ type: "message", content: "Hello" });

    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("streamUrl not configured"));
    warnSpy.mockRestore();
    t.dispose();
  });
});
