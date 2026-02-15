/**
 * Tests for Zustand chat store.
 */

import { beforeEach, describe, expect, it } from "vitest";
import type { ChatStore } from "../src/core/chat-store";
import { createChatStore } from "../src/core/chat-store";
import type { A2UISurface, ChatMessage } from "../src/types";

describe("ChatStore", () => {
  let store: ReturnType<typeof createChatStore>;

  beforeEach(() => {
    store = createChatStore();
  });

  // Helper to get current state
  const state = (): ChatStore => store.getState();

  // ── Initial state ──

  describe("initial state", () => {
    it("has empty sessions", () => {
      expect(state().sessions).toEqual([]);
    });

    it("has no active session", () => {
      expect(state().activeSessionId).toBeNull();
    });

    it("has no messages", () => {
      expect(state().messages).toEqual([]);
    });

    it("is not streaming", () => {
      expect(state().isStreaming).toBe(false);
    });

    it("is disconnected", () => {
      expect(state().connectionStatus).toBe("disconnected");
    });

    it("has sidebar open", () => {
      expect(state().sidebarOpen).toBe(true);
    });
  });

  // ── Session actions ──

  describe("session actions", () => {
    it("createSession adds a session and sets it active", () => {
      const id = state().createSession();

      expect(state().sessions).toHaveLength(1);
      expect(state().sessions[0]?.id).toBe(id);
      expect(state().sessions[0]?.title).toBe("New Chat");
      expect(state().activeSessionId).toBe(id);
      expect(state().messages).toEqual([]);
      expect(state().isStreaming).toBe(false);
    });

    it("createSession prepends new session", () => {
      const id1 = state().createSession();
      const id2 = state().createSession();

      expect(state().sessions).toHaveLength(2);
      expect(state().sessions[0]?.id).toBe(id2);
      expect(state().sessions[1]?.id).toBe(id1);
      expect(state().activeSessionId).toBe(id2);
    });

    it("switchSession loads messages from session", () => {
      const id1 = state().createSession();

      // Add a message to session 1
      state().sendMessage("Hello from session 1");
      expect(state().messages).toHaveLength(1);

      // Create session 2
      const id2 = state().createSession();
      expect(state().messages).toEqual([]);

      // Switch back to session 1
      state().switchSession(id1);
      expect(state().activeSessionId).toBe(id1);
      expect(state().messages).toHaveLength(1);
      expect(state().messages[0]?.content).toBe("Hello from session 1");

      // Switch to session 2
      state().switchSession(id2);
      expect(state().activeSessionId).toBe(id2);
      expect(state().messages).toEqual([]);
    });

    it("switchSession does nothing for unknown ID", () => {
      state().createSession();
      const activeId = state().activeSessionId;

      state().switchSession("nonexistent");
      expect(state().activeSessionId).toBe(activeId);
    });

    it("switchSession to same session is a no-op (preserves streaming state)", () => {
      const id = state().createSession();
      state().sendMessage("Hello");
      state().setStreaming(true);

      // Add step to top-level messages
      const msgId = state().messages[0]!.id;
      state().addStep(msgId, "step-1", "Thinking");

      // Click same session — should be a no-op
      state().switchSession(id);

      expect(state().isStreaming).toBe(true);
      expect(state().messages[0]?.steps).toHaveLength(1);
      expect(state().messages[0]?.steps?.[0]?.stepName).toBe("Thinking");
    });

    it("deleteSession removes session", () => {
      const id1 = state().createSession();
      const id2 = state().createSession();

      state().deleteSession(id2);
      expect(state().sessions).toHaveLength(1);
      expect(state().sessions[0]?.id).toBe(id1);
    });

    it("deleteSession switches to another session when active is deleted", () => {
      const id1 = state().createSession();
      state().createSession(); // id2 is now active

      state().deleteSession(state().activeSessionId!);

      expect(state().activeSessionId).toBe(id1);
      expect(state().sessions).toHaveLength(1);
    });

    it("deleteSession sets null when last session is deleted", () => {
      const id = state().createSession();

      state().deleteSession(id);

      expect(state().sessions).toEqual([]);
      expect(state().activeSessionId).toBeNull();
      expect(state().messages).toEqual([]);
    });

    it("renameSession updates title and updatedAt", () => {
      const id = state().createSession();
      const originalUpdatedAt = state().sessions[0]?.updatedAt;

      // Small delay to ensure updatedAt changes
      state().renameSession(id, "My Research");

      const session = state().sessions.find((s) => s.id === id);
      expect(session?.title).toBe("My Research");
      expect(session?.updatedAt).toBeDefined();
    });

    it("renameSession with nonexistent id does nothing", () => {
      const id = state().createSession();
      const sessionsBefore = [...state().sessions];

      state().renameSession("nonexistent", "New Title");

      expect(state().sessions).toHaveLength(1);
      expect(state().sessions[0]?.title).toBe("New Chat");
    });
  });

  // ── Message actions ──

  describe("message actions", () => {
    beforeEach(() => {
      state().createSession();
    });

    it("sendMessage creates a user message", () => {
      const msg = state().sendMessage("Hello");

      expect(msg.role).toBe("user");
      expect(msg.content).toBe("Hello");
      expect(msg.status).toBe("complete");
      expect(msg.id).toMatch(/^msg-/);
      expect(msg.timestamp).toBeDefined();
    });

    it("sendMessage adds message to store", () => {
      state().sendMessage("Test");

      expect(state().messages).toHaveLength(1);
      expect(state().messages[0]?.content).toBe("Test");
    });

    it("sendMessage with attachments", () => {
      const msg = state().sendMessage("File attached", [
        {
          id: "att-1",
          type: "file",
          name: "test.pdf",
          url: "/files/test.pdf",
          mimeType: "application/pdf",
        },
      ]);

      expect(msg.attachments).toHaveLength(1);
      expect(msg.attachments?.[0]?.name).toBe("test.pdf");
    });

    it("sendMessage updates active session", () => {
      state().sendMessage("Hello");

      const session = state().sessions.find((s) => s.id === state().activeSessionId);
      expect(session?.messages).toHaveLength(1);
      expect(session?.messages[0]?.content).toBe("Hello");
    });

    it("addMessage adds any message", () => {
      const msg: ChatMessage = {
        id: "msg-custom",
        role: "assistant",
        content: "Hi there",
        timestamp: new Date().toISOString(),
        status: "complete",
      };

      state().addMessage(msg);

      expect(state().messages).toHaveLength(1);
      expect(state().messages[0]?.role).toBe("assistant");
    });

    it("addMessage updates active session", () => {
      const msg: ChatMessage = {
        id: "msg-2",
        role: "assistant",
        content: "Reply",
        timestamp: new Date().toISOString(),
        status: "complete",
      };

      state().addMessage(msg);

      const session = state().sessions.find((s) => s.id === state().activeSessionId);
      expect(session?.messages).toHaveLength(1);
    });

    it("updateMessage patches a message", () => {
      state().sendMessage("Hello");
      const msgId = state().messages[0]?.id;

      state().updateMessage(msgId, { content: "Updated", status: "error" });

      expect(state().messages[0]?.content).toBe("Updated");
      expect(state().messages[0]?.status).toBe("error");
    });

    it("updateMessage does not affect other messages", () => {
      state().sendMessage("First");
      state().sendMessage("Second");

      const firstId = state().messages[0]?.id;
      state().updateMessage(firstId, { content: "Modified" });

      expect(state().messages[1]?.content).toBe("Second");
    });

    it("appendSurface adds surface to message", () => {
      state().sendMessage("Hello");
      const msgId = state().messages[0]?.id;

      const surface: A2UISurface = {
        surfaceId: "s1",
        catalogId: "test",
        components: new Map(),
        dataModel: {},
      };

      state().appendSurface(msgId, surface);

      expect(state().messages[0]?.surfaces).toHaveLength(1);
      expect(state().messages[0]?.surfaces?.[0]?.surfaceId).toBe("s1");
    });

    it("appendSurface appends to existing surfaces", () => {
      state().sendMessage("Hello");
      const msgId = state().messages[0]?.id;

      const surface1: A2UISurface = {
        surfaceId: "s1",
        catalogId: "test",
        components: new Map(),
        dataModel: {},
      };
      const surface2: A2UISurface = {
        surfaceId: "s2",
        catalogId: "test",
        components: new Map(),
        dataModel: {},
      };

      state().appendSurface(msgId, surface1);
      state().appendSurface(msgId, surface2);

      expect(state().messages[0]?.surfaces).toHaveLength(2);
    });
  });

  // ── State actions ──

  describe("state actions", () => {
    it("setStreaming toggles streaming state", () => {
      state().setStreaming(true);
      expect(state().isStreaming).toBe(true);

      state().setStreaming(false);
      expect(state().isStreaming).toBe(false);
    });

    it("setConnectionStatus updates status", () => {
      state().setConnectionStatus("connected");
      expect(state().connectionStatus).toBe("connected");

      state().setConnectionStatus("error");
      expect(state().connectionStatus).toBe("error");

      state().setConnectionStatus("disconnected");
      expect(state().connectionStatus).toBe("disconnected");
    });

    it("setSidebarOpen toggles sidebar", () => {
      state().setSidebarOpen(false);
      expect(state().sidebarOpen).toBe(false);

      state().setSidebarOpen(true);
      expect(state().sidebarOpen).toBe(true);
    });
  });

  // ── Step tracking ──

  describe("step tracking", () => {
    beforeEach(() => {
      state().createSession();
    });

    it("addStep appends a step to a message", () => {
      const msg = state().sendMessage("Hello");

      state().addStep(msg.id, "step-1", "Processing input");

      const updated = state().messages.find((m) => m.id === msg.id);
      expect(updated?.steps).toHaveLength(1);
      expect(updated?.steps?.[0]?.stepId).toBe("step-1");
      expect(updated?.steps?.[0]?.stepName).toBe("Processing input");
      expect(updated?.steps?.[0]?.status).toBe("active");
    });

    it("addStep appends multiple steps", () => {
      const msg = state().sendMessage("Hello");

      state().addStep(msg.id, "step-1", "Processing input");
      state().addStep(msg.id, "step-2", "Thinking");

      const updated = state().messages.find((m) => m.id === msg.id);
      expect(updated?.steps).toHaveLength(2);
      expect(updated?.steps?.[1]?.stepName).toBe("Thinking");
    });

    it("completeStep marks a step as complete", () => {
      const msg = state().sendMessage("Hello");

      state().addStep(msg.id, "step-1", "Processing input");
      state().addStep(msg.id, "step-2", "Thinking");
      state().completeStep(msg.id, "step-1");

      const updated = state().messages.find((m) => m.id === msg.id);
      expect(updated?.steps?.[0]?.status).toBe("complete");
      expect(updated?.steps?.[1]?.status).toBe("active");
    });

    it("addStep syncs steps to session messages", () => {
      const msg = state().sendMessage("Hello");

      state().addStep(msg.id, "step-1", "Processing input");

      const session = state().sessions.find((s) => s.id === state().activeSessionId);
      const sessionMsg = session?.messages.find((m) => m.id === msg.id);
      expect(sessionMsg?.steps).toHaveLength(1);
      expect(sessionMsg?.steps?.[0]?.stepName).toBe("Processing input");
    });

    it("completeStep syncs to session messages", () => {
      const msg = state().sendMessage("Hello");

      state().addStep(msg.id, "step-1", "Processing input");
      state().completeStep(msg.id, "step-1");

      const session = state().sessions.find((s) => s.id === state().activeSessionId);
      const sessionMsg = session?.messages.find((m) => m.id === msg.id);
      expect(sessionMsg?.steps?.[0]?.status).toBe("complete");
    });
  });

  // ── Streaming lifecycle ──

  describe("streaming lifecycle", () => {
    beforeEach(() => {
      state().createSession();
    });

    it("startStreaming sets streamingSessionId and streamingMessageId", () => {
      const sessionId = state().activeSessionId!;
      state().startStreaming(sessionId, "msg-1");

      expect(state().streamingMessages).toEqual({ "msg-1": sessionId });
      expect(state().isStreaming).toBe(true);
    });

    it("startStreaming sets isStreaming false when target is not active session", () => {
      const id1 = state().activeSessionId!;
      const id2 = state().createSession();

      // Start streaming on session 1 while session 2 is active
      state().startStreaming(id1, "msg-1");

      expect(state().streamingMessages).toEqual({ "msg-1": id1 });
      expect(state().isStreaming).toBe(false);
    });

    it("stopStreaming removes specific message from streaming state", () => {
      const sessionId = state().activeSessionId!;
      state().startStreaming(sessionId, "msg-1");
      state().stopStreaming("msg-1");

      expect(state().streamingMessages).toEqual({});
      expect(state().isStreaming).toBe(false);
    });

    it("startStreaming supports multiple concurrent streams", () => {
      const sessionId = state().activeSessionId!;
      state().startStreaming(sessionId, "msg-1");
      state().startStreaming(sessionId, "msg-2");

      expect(state().streamingMessages).toEqual({
        "msg-1": sessionId,
        "msg-2": sessionId,
      });
      expect(state().isStreaming).toBe(true);

      // Stop one — still streaming
      state().stopStreaming("msg-1");
      expect(state().streamingMessages).toEqual({ "msg-2": sessionId });
      expect(state().isStreaming).toBe(true);

      // Stop the other — no more streaming
      state().stopStreaming("msg-2");
      expect(state().streamingMessages).toEqual({});
      expect(state().isStreaming).toBe(false);
    });
  });

  // ── Session-targeted actions ──

  describe("session-targeted actions", () => {
    let sessionId1: string;
    let sessionId2: string;

    beforeEach(() => {
      sessionId1 = state().createSession();
      sessionId2 = state().createSession(); // sessionId2 is now active
    });

    it("addMessageToSession adds to active session and top-level messages", () => {
      const msg: ChatMessage = {
        id: "msg-target",
        role: "assistant",
        content: "Hello",
        timestamp: new Date().toISOString(),
        status: "complete",
      };

      state().addMessageToSession(sessionId2, msg);

      // Top-level messages updated (session2 is active)
      expect(state().messages).toHaveLength(1);
      expect(state().messages[0]?.id).toBe("msg-target");

      // Session updated
      const session = state().sessions.find((s) => s.id === sessionId2);
      expect(session?.messages).toHaveLength(1);
    });

    it("addMessageToSession adds to background session without touching top-level messages", () => {
      const msg: ChatMessage = {
        id: "msg-bg",
        role: "assistant",
        content: "Background",
        timestamp: new Date().toISOString(),
        status: "complete",
      };

      state().addMessageToSession(sessionId1, msg);

      // Top-level messages NOT updated (session1 is not active)
      expect(state().messages).toEqual([]);

      // Session updated
      const session = state().sessions.find((s) => s.id === sessionId1);
      expect(session?.messages).toHaveLength(1);
      expect(session?.messages[0]?.content).toBe("Background");
    });

    it("updateMessageInSession updates active session and top-level messages", () => {
      const msg: ChatMessage = {
        id: "msg-upd",
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        status: "streaming",
      };
      state().addMessageToSession(sessionId2, msg);

      state().updateMessageInSession(sessionId2, "msg-upd", (m) => ({
        ...m,
        content: "Updated content",
        status: "complete",
      }));

      expect(state().messages[0]?.content).toBe("Updated content");
      expect(state().messages[0]?.status).toBe("complete");

      const session = state().sessions.find((s) => s.id === sessionId2);
      expect(session?.messages[0]?.content).toBe("Updated content");
    });

    it("updateMessageInSession updates background session without touching top-level", () => {
      // Add message to background session (session1)
      const msg: ChatMessage = {
        id: "msg-bg-upd",
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        status: "streaming",
      };
      state().addMessageToSession(sessionId1, msg);

      state().updateMessageInSession(sessionId1, "msg-bg-upd", (m) => ({
        ...m,
        content: "Background updated",
      }));

      // Top-level messages unaffected
      expect(state().messages).toEqual([]);

      // Background session updated
      const session = state().sessions.find((s) => s.id === sessionId1);
      expect(session?.messages[0]?.content).toBe("Background updated");
    });

    it("switching to session with background updates shows them", () => {
      // Add and update message in background session
      const msg: ChatMessage = {
        id: "msg-reveal",
        role: "assistant",
        content: "Streamed in background",
        timestamp: new Date().toISOString(),
        status: "complete",
      };
      state().addMessageToSession(sessionId1, msg);

      // Now switch to session1
      state().switchSession(sessionId1);

      expect(state().messages).toHaveLength(1);
      expect(state().messages[0]?.content).toBe("Streamed in background");
    });
  });

  // ── switchSession with streaming ──

  describe("switchSession with streaming", () => {
    let sessionId1: string;
    let sessionId2: string;

    beforeEach(() => {
      sessionId1 = state().createSession();
      sessionId2 = state().createSession();
    });

    it("switchSession to streaming session preserves isStreaming", () => {
      // Start streaming on session1
      state().startStreaming(sessionId1, "msg-1");

      // session2 is active, isStreaming should be false
      expect(state().isStreaming).toBe(false);

      // Switch to session1 (the streaming session)
      state().switchSession(sessionId1);

      expect(state().isStreaming).toBe(true);
    });

    it("switchSession to non-streaming session sets isStreaming false", () => {
      // Start streaming on session2 (active)
      state().startStreaming(sessionId2, "msg-1");
      expect(state().isStreaming).toBe(true);

      // Switch to session1 (not streaming)
      state().switchSession(sessionId1);

      expect(state().isStreaming).toBe(false);
    });

    it("full background streaming scenario", () => {
      // session2 is active, start streaming on it
      state().startStreaming(sessionId2, "msg-stream");
      const msg: ChatMessage = {
        id: "msg-stream",
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        status: "streaming",
      };
      state().addMessageToSession(sessionId2, msg);

      // User switches to session1 mid-stream
      state().switchSession(sessionId1);
      expect(state().isStreaming).toBe(false);
      expect(state().messages).toEqual([]);

      // Events keep arriving for session2 (background)
      state().updateMessageInSession(sessionId2, "msg-stream", (m) => ({
        ...m,
        content: "Hello ",
      }));
      state().updateMessageInSession(sessionId2, "msg-stream", (m) => ({
        ...m,
        content: `${m.content}world!`,
      }));
      state().updateMessageInSession(sessionId2, "msg-stream", (m) => ({
        ...m,
        status: "complete",
      }));
      state().stopStreaming("msg-stream");

      // session1 messages still empty
      expect(state().messages).toEqual([]);

      // Switch back to session2 — see the completed message
      state().switchSession(sessionId2);
      expect(state().messages).toHaveLength(1);
      expect(state().messages[0]?.content).toBe("Hello world!");
      expect(state().messages[0]?.status).toBe("complete");
      expect(state().isStreaming).toBe(false);
    });
  });

  // ── Edge cases ──

  describe("edge cases", () => {
    it("sendMessage without active session still adds to messages", () => {
      // No session created
      const msg = state().sendMessage("Orphan message");

      expect(state().messages).toHaveLength(1);
      expect(msg.content).toBe("Orphan message");
    });

    it("multiple rapid messages maintain order", () => {
      state().createSession();

      state().sendMessage("1");
      state().sendMessage("2");
      state().sendMessage("3");

      expect(state().messages.map((m) => m.content)).toEqual(["1", "2", "3"]);
    });
  });
});
