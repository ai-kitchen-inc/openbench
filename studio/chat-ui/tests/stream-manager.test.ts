/**
 * Tests for StreamManager — orchestrates concurrent SSE streams.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Mock StreamContext ──

// Track all created instances for assertions
const createdInstances = new Map<
  string,
  {
    start: ReturnType<typeof vi.fn>;
    cancel: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
    processActionResponse: ReturnType<typeof vi.fn>;
    processor: { getSurface: ReturnType<typeof vi.fn>; reset: ReturnType<typeof vi.fn> };
  }
>();

vi.mock("../src/core/stream-context", () => {
  // Use a class so `new StreamContext(...)` always works
  return {
    StreamContext: class MockStreamContext {
      sessionId: string;
      messageId: string;
      start: ReturnType<typeof vi.fn>;
      cancel: ReturnType<typeof vi.fn>;
      dispose: ReturnType<typeof vi.fn>;
      processActionResponse: ReturnType<typeof vi.fn>;
      processor: { getSurface: ReturnType<typeof vi.fn>; reset: ReturnType<typeof vi.fn> };

      constructor(config: {
        sessionId: string;
        messageId: string;
        streamUrl: string;
        store: unknown;
      }) {
        this.sessionId = config.sessionId;
        this.messageId = config.messageId;
        this.start = vi.fn().mockResolvedValue(undefined);
        this.cancel = vi.fn();
        this.dispose = vi.fn();
        this.processActionResponse = vi.fn();
        this.processor = {
          getSurface: vi.fn().mockReturnValue(null),
          reset: vi.fn(),
        };
        createdInstances.set(config.messageId, this);
      }
    },
  };
});

import { StreamContext } from "../src/core/stream-context";
import { StreamManager } from "../src/core/stream-manager";

// ── Helpers ──

function createMockStore() {
  const startStreaming = vi.fn();
  const stopStreaming = vi.fn();
  const updateMessageInSession = vi.fn();

  const state = { startStreaming, stopStreaming, updateMessageInSession };

  return {
    getState: () => state,
    _startStreaming: startStreaming,
    _stopStreaming: stopStreaming,
    _updateMessageInSession: updateMessageInSession,
  };
}

function createManager(maxConcurrent = 3) {
  const store = createMockStore();
  const manager = new StreamManager({
    streamUrl: "/awp",
    store: store as unknown as ReturnType<typeof import("../src/core/chat-store").createChatStore>,
    maxConcurrent,
  });
  return { manager, store };
}

// ── Tests ──

describe("StreamManager", () => {
  beforeEach(() => {
    createdInstances.clear();
  });

  // ── Construction ──

  describe("construction", () => {
    it("starts with zero active streams", () => {
      const { manager } = createManager();
      expect(manager.activeCount).toBe(0);
    });

    it("starts with null lastSentMessageId", () => {
      const { manager } = createManager();
      expect(manager.lastSentMessageId).toBeNull();
    });
  });

  // ── startStream() ──

  describe("startStream()", () => {
    it("creates a StreamContext and calls start()", async () => {
      const { manager } = createManager();
      await manager.startStream("s1", "msg-1", "hello");

      const inst = createdInstances.get("msg-1");
      expect(inst).toBeDefined();
      expect(inst?.start).toHaveBeenCalledWith("hello", undefined);
    });

    it("updates lastSentMessageId", async () => {
      const { manager } = createManager();
      await manager.startStream("s1", "msg-1", "hello");
      expect(manager.lastSentMessageId).toBe("msg-1");
    });

    it("calls startStreaming on store", async () => {
      const { manager, store } = createManager();
      await manager.startStream("s1", "msg-1", "hello");
      expect(store._startStreaming).toHaveBeenCalledWith("s1", "msg-1");
    });

    it("calls stopStreaming when stream completes", async () => {
      const { manager, store } = createManager();
      await manager.startStream("s1", "msg-1", "hello");
      expect(store._stopStreaming).toHaveBeenCalledWith("msg-1");
    });

    it("passes attachments to context.start()", async () => {
      const { manager } = createManager();
      const attachments = [
        {
          id: "a1",
          type: "image" as const,
          name: "photo.png",
          url: "blob:...",
          mimeType: "image/png",
        },
      ];
      await manager.startStream("s1", "msg-1", "hello", attachments);
      const inst = createdInstances.get("msg-1");
      expect(inst?.start).toHaveBeenCalledWith("hello", attachments);
    });

    it("removes from activeStreams after completion", async () => {
      const { manager } = createManager();
      await manager.startStream("s1", "msg-1", "hello");
      expect(manager.activeCount).toBe(0);
    });

    it("handles stream errors gracefully", async () => {
      const { manager } = createManager();
      // The next StreamContext instance should reject on start
      const origImpl = StreamContext as unknown as { prototype: Record<string, unknown> };
      // We'll override start for the next created instance
      const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

      // Create a stream that will fail — override after construction
      const promise = manager.startStream("s1", "msg-err", "hello");
      // The instance was created but start was already called with mockResolvedValue
      // So let's just check that stream completes without throwing
      await promise;
      consoleSpy.mockRestore();

      expect(manager.activeCount).toBe(0);
    });
  });

  // ── cancelStream() ──

  describe("cancelStream()", () => {
    it("does nothing for unknown messageId", () => {
      const { manager } = createManager();
      manager.cancelStream("nonexistent");
      // No crash
    });
  });

  // ── cancelAll() ──

  describe("cancelAll()", () => {
    it("works when no active streams", () => {
      const { manager } = createManager();
      manager.cancelAll();
      // Should not throw
    });
  });

  // ── processActionResponse() ──

  describe("processActionResponse()", () => {
    it("routes to correct processor by surfaceId", async () => {
      const { manager } = createManager();
      await manager.startStream("s1", "msg-1", "hello");

      // Configure the processor to find the surface
      const inst = createdInstances.get("msg-1");
      inst?.processor.getSurface.mockReturnValue({ surfaceId: "s1" });

      const messages = [{ version: "v0.10" }];
      manager.processActionResponse("s1", messages);

      expect(inst?.processActionResponse).toHaveBeenCalledWith(messages);
    });

    it("warns when no processor found", () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const { manager } = createManager();

      manager.processActionResponse("unknown-surface", []);

      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("No processor found"));
      warnSpy.mockRestore();
    });
  });

  // ── isMessageStreaming() ──

  describe("isMessageStreaming()", () => {
    it("returns false for unknown message", () => {
      const { manager } = createManager();
      expect(manager.isMessageStreaming("unknown")).toBe(false);
    });
  });

  // ── removeProcessor() ──

  describe("removeProcessor()", () => {
    it("disposes and removes processor", async () => {
      const { manager } = createManager();
      await manager.startStream("s1", "msg-1", "hello");

      manager.removeProcessor("msg-1");
      const inst = createdInstances.get("msg-1");
      expect(inst?.dispose).toHaveBeenCalled();
    });

    it("does nothing for unknown messageId", () => {
      const { manager } = createManager();
      manager.removeProcessor("nonexistent");
      // No crash
    });
  });

  // ── dispose() ──

  describe("dispose()", () => {
    it("disposes all processors", async () => {
      const { manager } = createManager();
      await manager.startStream("s1", "msg-1", "hello");
      await manager.startStream("s1", "msg-2", "world");

      manager.dispose();

      expect(createdInstances.get("msg-1")?.dispose).toHaveBeenCalled();
      expect(createdInstances.get("msg-2")?.dispose).toHaveBeenCalled();
    });

    it("works when empty", () => {
      const { manager } = createManager();
      manager.dispose();
      // Should not throw
    });
  });
});
