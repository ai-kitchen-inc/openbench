/**
 * Tests for StreamContext — isolated per-message SSE state.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../src/types";

// ── Mock @ag-ui/client ──

vi.mock("@ag-ui/client", () => ({
  HttpAgent: vi.fn(),
}));

import { HttpAgent } from "@ag-ui/client";

// ── Mock @ag-ui/core ──

vi.mock("@ag-ui/core", () => ({
  EventType: {
    RUN_STARTED: "RUN_STARTED",
    STEP_STARTED: "STEP_STARTED",
    STEP_FINISHED: "STEP_FINISHED",
    CUSTOM: "CUSTOM",
    TEXT_MESSAGE_CONTENT: "TEXT_MESSAGE_CONTENT",
    RUN_FINISHED: "RUN_FINISHED",
    RUN_ERROR: "RUN_ERROR",
  },
}));

// ── Mock utils ──

let idCounter = 0;
vi.mock("../src/core/utils", () => ({
  generateId: () => `id-${idCounter++}`,
}));

import { StreamContext } from "../src/core/stream-context";

// ── Helpers ──

type Observer = {
  next: (event: Record<string, unknown>) => void;
  error: (err: Error) => void;
  complete: () => void;
};

function createMockStore() {
  const messages = new Map<string, ChatMessage>();
  const updateMessageInSession = vi.fn(
    (_sid: string, mid: string, updater: (msg: ChatMessage) => ChatMessage) => {
      const existing =
        messages.get(mid) ||
        ({
          id: mid,
          role: "assistant",
          content: "",
          status: "streaming",
          createdAt: "",
        } as ChatMessage);
      messages.set(mid, updater(existing));
    },
  );
  const startStreaming = vi.fn();
  const stopStreaming = vi.fn();

  // Return the SAME state object every time getState() is called
  const state = { updateMessageInSession, startStreaming, stopStreaming };

  return {
    getState: () => state,
    _messages: messages,
    _updateMessageInSession: updateMessageInSession,
    _startStreaming: startStreaming,
    _stopStreaming: stopStreaming,
  };
}

function setupHttpAgent(events: Record<string, unknown>[]) {
  const unsubscribe = vi.fn();
  const MockedHttpAgent = HttpAgent as unknown as ReturnType<typeof vi.fn>;
  MockedHttpAgent.mockImplementation(() => ({
    run: () => ({
      subscribe: (observer: Observer) => {
        for (const event of events) {
          observer.next(event);
        }
        observer.complete();
        return { unsubscribe };
      },
    }),
  }));
  return { unsubscribe };
}

function setupHttpAgentAsync() {
  let capturedObserver: Observer | null = null;
  const unsubscribe = vi.fn();
  const MockedHttpAgent = HttpAgent as unknown as ReturnType<typeof vi.fn>;
  MockedHttpAgent.mockImplementation(() => ({
    run: () => ({
      subscribe: (observer: Observer) => {
        capturedObserver = observer;
        return { unsubscribe };
      },
    }),
  }));
  return {
    unsubscribe,
    emit: (event: Record<string, unknown>) => capturedObserver?.next(event),
    complete: () => capturedObserver?.complete(),
    error: (err: Error) => capturedObserver?.error(err),
  };
}

function setupHttpAgentError(err: Error) {
  const MockedHttpAgent = HttpAgent as unknown as ReturnType<typeof vi.fn>;
  MockedHttpAgent.mockImplementation(() => ({
    run: () => ({
      subscribe: (observer: Observer) => {
        observer.error(err);
        return { unsubscribe: vi.fn() };
      },
    }),
  }));
}

// ── Tests ──

describe("StreamContext", () => {
  let store: ReturnType<typeof createMockStore>;

  beforeEach(() => {
    idCounter = 0;
    store = createMockStore();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function createContext(messageId = "msg-1", sessionId = "session-1") {
    return new StreamContext({
      sessionId,
      messageId,
      streamUrl: "/awp",
      store: store as unknown as ReturnType<
        typeof import("../src/core/chat-store").createChatStore
      >,
    });
  }

  // ── Construction ──

  describe("construction", () => {
    it("stores sessionId and messageId", () => {
      const ctx = createContext("msg-1", "session-1");
      expect(ctx.sessionId).toBe("session-1");
      expect(ctx.messageId).toBe("msg-1");
    });

    it("creates a fresh processor", () => {
      const ctx = createContext();
      expect(ctx.processor).toBeDefined();
    });

    it("starts not disposed", () => {
      const ctx = createContext();
      expect(ctx.disposed).toBe(false);
    });
  });

  // ── start() ──

  describe("start()", () => {
    it("resolves on successful stream completion", async () => {
      setupHttpAgent([{ type: "RUN_STARTED" }, { type: "RUN_FINISHED" }]);
      const ctx = createContext();
      await expect(ctx.start("hello")).resolves.toBeUndefined();
    });

    it("rejects on stream error", async () => {
      setupHttpAgentError(new Error("connection lost"));
      const ctx = createContext();
      await expect(ctx.start("hello")).rejects.toThrow("connection lost");
    });

    it("does nothing if already disposed", async () => {
      setupHttpAgent([]);
      const ctx = createContext();
      ctx.dispose();
      await ctx.start("hello");
      // Should not throw — silently returns
    });
  });

  // ── Event handling ──

  describe("event handling", () => {
    it("handles STEP_STARTED by adding step", async () => {
      setupHttpAgent([
        { type: "RUN_STARTED" },
        { type: "STEP_STARTED", stepName: "Processing" },
        { type: "RUN_FINISHED" },
      ]);
      const ctx = createContext();
      await ctx.start("hello");

      expect(store._updateMessageInSession).toHaveBeenCalled();

      // Check the step was added
      const msg = store._messages.get("msg-1");
      expect(msg?.steps).toBeDefined();
      expect(msg?.steps?.length).toBeGreaterThanOrEqual(1);
    });

    it("handles STEP_FINISHED by completing active step", async () => {
      setupHttpAgent([
        { type: "RUN_STARTED" },
        { type: "STEP_STARTED", stepName: "Thinking" },
        { type: "STEP_FINISHED" },
        { type: "RUN_FINISHED" },
      ]);
      const ctx = createContext();
      await ctx.start("hello");

      const msg = store._messages.get("msg-1");
      const completedSteps = msg?.steps?.filter((s) => s.status === "complete") ?? [];
      expect(completedSteps.length).toBeGreaterThanOrEqual(1);
    });

    it("handles TEXT_MESSAGE_CONTENT by appending delta", async () => {
      setupHttpAgent([
        { type: "RUN_STARTED" },
        { type: "TEXT_MESSAGE_CONTENT", delta: "Hello" },
        { type: "TEXT_MESSAGE_CONTENT", delta: " World" },
        { type: "RUN_FINISHED" },
      ]);
      const ctx = createContext();
      await ctx.start("hi");

      const msg = store._messages.get("msg-1");
      expect(msg?.content).toBe("Hello World");
    });

    it("handles CUSTOM a2ui events", async () => {
      setupHttpAgent([
        { type: "RUN_STARTED" },
        {
          type: "CUSTOM",
          name: "a2ui",
          value: {
            version: "v0.10",
            createSurface: { surfaceId: "s1", catalogId: "default" },
          },
        },
        { type: "RUN_FINISHED" },
      ]);
      const ctx = createContext();
      await ctx.start("hi");

      const surface = ctx.processor.getSurface("s1");
      expect(surface).toBeDefined();
    });

    it("ignores CUSTOM events with non-a2ui name", async () => {
      setupHttpAgent([
        { type: "RUN_STARTED" },
        { type: "CUSTOM", name: "other", value: {} },
        { type: "RUN_FINISHED" },
      ]);
      const ctx = createContext();
      await ctx.start("hi");
      // Should not throw
    });

    it("handles RUN_FINISHED with result content", async () => {
      setupHttpAgent([
        { type: "RUN_STARTED" },
        {
          type: "RUN_FINISHED",
          result: { content: "final answer", metadata: { key: "val" } },
        },
      ]);
      const ctx = createContext();
      await ctx.start("hi");

      const msg = store._messages.get("msg-1");
      expect(msg?.status).toBe("complete");
    });

    it("handles RUN_ERROR", async () => {
      setupHttpAgent([{ type: "RUN_STARTED" }, { type: "RUN_ERROR", message: "something failed" }]);
      const ctx = createContext();
      await ctx.start("hi");

      const msg = store._messages.get("msg-1");
      expect(msg?.status).toBe("error");
    });

    it("marks RUN_ERROR message metadata as aborted so the retry UI can key off it", async () => {
      setupHttpAgent([{ type: "RUN_STARTED" }, { type: "RUN_ERROR", message: "Gemini 500" }]);
      const ctx = createContext();
      await ctx.start("hi");

      const msg = store._messages.get("msg-1");
      expect(msg?.status).toBe("error");
      expect(msg?.metadata?.aborted).toBe(true);
      expect(msg?.metadata?.error).toContain("Gemini 500");
    });

    it("ignores events after disposal", async () => {
      const ctrl = setupHttpAgentAsync();
      const ctx = createContext();
      const promise = ctx.start("hi");

      ctrl.emit({ type: "RUN_STARTED" });
      ctx.dispose();
      ctrl.emit({ type: "TEXT_MESSAGE_CONTENT", delta: "ignored" });
      ctrl.complete();

      await promise;
      const msg = store._messages.get("msg-1");
      expect(msg?.content ?? "").toBe("");
    });
  });

  // ── cancel() ──

  describe("cancel()", () => {
    it("unsubscribes from the SSE stream", async () => {
      const ctrl = setupHttpAgentAsync();
      const ctx = createContext();
      const promise = ctx.start("hi");

      ctrl.emit({ type: "RUN_STARTED" });
      ctx.cancel();
      ctrl.complete();

      await promise;
      expect(ctrl.unsubscribe).toHaveBeenCalled();
    });

    it("does not mark as disposed", () => {
      const ctx = createContext();
      ctx.cancel();
      expect(ctx.disposed).toBe(false);
    });
  });

  // ── dispose() ──

  describe("dispose()", () => {
    it("marks as disposed", () => {
      const ctx = createContext();
      ctx.dispose();
      expect(ctx.disposed).toBe(true);
    });

    it("cancels subscription and resets processor", () => {
      const ctx = createContext();
      const resetSpy = vi.spyOn(ctx.processor, "reset");
      ctx.dispose();
      expect(resetSpy).toHaveBeenCalled();
    });
  });

  // ── processActionResponse() ──

  describe("processActionResponse()", () => {
    it("processes A2UI messages through the processor", async () => {
      setupHttpAgent([
        { type: "RUN_STARTED" },
        {
          type: "CUSTOM",
          name: "a2ui",
          value: {
            version: "v0.10",
            createSurface: { surfaceId: "s1", catalogId: "default" },
          },
        },
        { type: "RUN_FINISHED" },
      ]);
      const ctx = createContext();
      await ctx.start("hi");

      ctx.processActionResponse([
        {
          version: "v0.10",
          updateDataModel: {
            surfaceId: "s1",
            dataModel: { "/status": "updated" },
          },
        },
      ]);

      expect(ctx.processor.getSurface("s1")).toBeDefined();
    });

    it("does nothing if disposed", async () => {
      setupHttpAgent([{ type: "RUN_STARTED" }, { type: "RUN_FINISHED" }]);
      const ctx = createContext();
      await ctx.start("hi");

      ctx.dispose();
      // Should not throw
      ctx.processActionResponse([{ version: "v0.10" }]);
    });
  });
});
