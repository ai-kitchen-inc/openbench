/**
 * Zustand store for chat state management.
 *
 * Manages sessions, messages, streaming state, and connection status.
 * Supports parallel streaming: multiple messages can stream concurrently,
 * each tracked independently in `streamingMessages`.
 */

import { createStore } from "zustand/vanilla";
import type {
  A2UISurface,
  Attachment,
  ChatMessage,
  ChatSession,
  StepInfo,
  TransportStatus,
} from "../types";
import { generateId, nowISO } from "./utils";

export interface ChatState {
  // Sessions
  sessions: ChatSession[];
  activeSessionId: string | null;

  // Messages (for active session)
  messages: ChatMessage[];
  isStreaming: boolean;
  connectionStatus: TransportStatus;

  // Parallel streaming: messageId -> sessionId
  streamingMessages: Record<string, string>;

  // UI
  sidebarOpen: boolean;
}

export interface ChatActions {
  // Message actions (operate on active session)
  sendMessage: (content: string, attachments?: Attachment[]) => ChatMessage;
  addMessage: (message: ChatMessage) => void;
  updateMessage: (id: string, patch: Partial<ChatMessage>) => void;
  appendSurface: (messageId: string, surface: A2UISurface) => void;
  addStep: (messageId: string, stepId: string, stepName: string) => void;
  completeStep: (messageId: string, stepId: string) => void;

  // Session-targeted actions (route to any session, active or background)
  addMessageToSession: (sessionId: string, message: ChatMessage) => void;
  updateMessageInSession: (
    sessionId: string,
    messageId: string,
    updater: (msg: ChatMessage) => ChatMessage,
  ) => void;

  // Streaming lifecycle (parallel-safe)
  startStreaming: (sessionId: string, messageId: string) => void;
  stopStreaming: (messageId: string) => void;

  // Session actions
  createSession: () => string;
  switchSession: (id: string) => void;
  deleteSession: (id: string) => void;
  renameSession: (id: string, newTitle: string) => void;

  // State actions
  setStreaming: (streaming: boolean) => void;
  setConnectionStatus: (status: TransportStatus) => void;
  setSidebarOpen: (open: boolean) => void;
}

export type ChatStore = ChatState & ChatActions;

/** Check if any streaming message belongs to the given session. */
function hasStreamingInSession(
  streamingMessages: Record<string, string>,
  sessionId: string,
): boolean {
  return Object.values(streamingMessages).includes(sessionId);
}

/**
 * Create a vanilla Zustand store for chat state.
 * Can be used with React via `useStore(chatStore)` or standalone.
 */
export function createChatStore() {
  return createStore<ChatStore>()((set, get) => ({
    // ── Initial state ──
    sessions: [],
    activeSessionId: null,
    messages: [],
    isStreaming: false,
    connectionStatus: "disconnected",
    streamingMessages: {},
    sidebarOpen: true,

    // ── Message actions (active session) ──

    sendMessage: (content: string, attachments?: Attachment[]) => {
      const message: ChatMessage = {
        id: generateId("msg"),
        role: "user",
        content,
        attachments,
        timestamp: nowISO(),
        status: "complete",
      };
      set((state) => ({
        messages: [...state.messages, message],
      }));

      // Also update the active session
      const { activeSessionId, sessions } = get();
      if (activeSessionId) {
        set({
          sessions: sessions.map((s) =>
            s.id === activeSessionId
              ? {
                  ...s,
                  messages: [...s.messages, message],
                  updatedAt: nowISO(),
                }
              : s,
          ),
        });
      }

      return message;
    },

    addMessage: (message: ChatMessage) => {
      set((state) => ({
        messages: [...state.messages, message],
      }));

      // Also update the active session
      const { activeSessionId, sessions } = get();
      if (activeSessionId) {
        set({
          sessions: sessions.map((s) =>
            s.id === activeSessionId
              ? {
                  ...s,
                  messages: [...s.messages, message],
                  updatedAt: nowISO(),
                }
              : s,
          ),
        });
      }
    },

    updateMessage: (id: string, patch: Partial<ChatMessage>) => {
      set((state) => ({
        messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
      }));

      // Sync update to the active session
      const { activeSessionId, sessions } = get();
      if (activeSessionId) {
        set({
          sessions: sessions.map((s) =>
            s.id === activeSessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
                  updatedAt: nowISO(),
                }
              : s,
          ),
        });
      }
    },

    appendSurface: (messageId: string, surface: A2UISurface) => {
      set((state) => ({
        messages: state.messages.map((m) =>
          m.id === messageId ? { ...m, surfaces: [...(m.surfaces ?? []), surface] } : m,
        ),
      }));
    },

    addStep: (messageId: string, stepId: string, stepName: string) => {
      const step: StepInfo = { stepId, stepName, status: "active" };
      set((state) => ({
        messages: state.messages.map((m) =>
          m.id === messageId ? { ...m, steps: [...(m.steps ?? []), step] } : m,
        ),
      }));

      // Sync to the active session
      const { activeSessionId, sessions } = get();
      if (activeSessionId) {
        set({
          sessions: sessions.map((s) =>
            s.id === activeSessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === messageId ? { ...m, steps: [...(m.steps ?? []), step] } : m,
                  ),
                }
              : s,
          ),
        });
      }
    },

    completeStep: (messageId: string, stepId: string) => {
      set((state) => ({
        messages: state.messages.map((m) =>
          m.id === messageId
            ? {
                ...m,
                steps: (m.steps ?? []).map((s) =>
                  s.stepId === stepId ? { ...s, status: "complete" as const } : s,
                ),
              }
            : m,
        ),
      }));

      // Sync to the active session
      const { activeSessionId, sessions } = get();
      if (activeSessionId) {
        set({
          sessions: sessions.map((s) =>
            s.id === activeSessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === messageId
                      ? {
                          ...m,
                          steps: (m.steps ?? []).map((st) =>
                            st.stepId === stepId ? { ...st, status: "complete" as const } : st,
                          ),
                        }
                      : m,
                  ),
                }
              : s,
          ),
        });
      }
    },

    // ── Session-targeted actions ──

    addMessageToSession: (sessionId: string, message: ChatMessage) => {
      const { activeSessionId } = get();
      const isActive = sessionId === activeSessionId;

      set((state) => ({
        sessions: state.sessions.map((s) =>
          s.id === sessionId
            ? { ...s, messages: [...s.messages, message], updatedAt: nowISO() }
            : s,
        ),
        ...(isActive ? { messages: [...state.messages, message] } : {}),
      }));
    },

    updateMessageInSession: (
      sessionId: string,
      messageId: string,
      updater: (msg: ChatMessage) => ChatMessage,
    ) => {
      const { activeSessionId } = get();
      const isActive = sessionId === activeSessionId;

      set((state) => ({
        sessions: state.sessions.map((s) =>
          s.id === sessionId
            ? {
                ...s,
                messages: s.messages.map((m) => (m.id === messageId ? updater(m) : m)),
                updatedAt: nowISO(),
              }
            : s,
        ),
        ...(isActive
          ? { messages: state.messages.map((m) => (m.id === messageId ? updater(m) : m)) }
          : {}),
      }));
    },

    // ── Streaming lifecycle (parallel-safe) ──

    startStreaming: (sessionId: string, messageId: string) => {
      const { activeSessionId } = get();
      set((state) => ({
        streamingMessages: { ...state.streamingMessages, [messageId]: sessionId },
        isStreaming: sessionId === activeSessionId || state.isStreaming,
      }));
    },

    stopStreaming: (messageId: string) => {
      const { activeSessionId } = get();
      set((state) => {
        const { [messageId]: _, ...rest } = state.streamingMessages;
        return {
          streamingMessages: rest,
          isStreaming: hasStreamingInSession(rest, activeSessionId ?? ""),
        };
      });
    },

    // ── Session actions ──

    createSession: () => {
      const id = generateId("session");
      const session: ChatSession = {
        id,
        title: "New Chat",
        messages: [],
        createdAt: nowISO(),
        updatedAt: nowISO(),
      };
      set((state) => ({
        sessions: [session, ...state.sessions],
        activeSessionId: id,
        messages: [],
        isStreaming: false,
      }));
      return id;
    },

    switchSession: (id: string) => {
      const { activeSessionId, sessions, streamingMessages } = get();
      if (id === activeSessionId) return;

      const session = sessions.find((s) => s.id === id);
      if (session) {
        set({
          activeSessionId: id,
          messages: [...session.messages],
          // isStreaming true if target session has any active streams
          isStreaming: hasStreamingInSession(streamingMessages, id),
        });
      }
    },

    deleteSession: (id: string) => {
      const { activeSessionId, sessions } = get();
      const filtered = sessions.filter((s) => s.id !== id);
      const newActive = activeSessionId === id ? (filtered[0]?.id ?? null) : activeSessionId;

      set({
        sessions: filtered,
        activeSessionId: newActive,
        messages: newActive ? (filtered.find((s) => s.id === newActive)?.messages ?? []) : [],
      });
    },

    renameSession: (id: string, newTitle: string) => {
      set((state) => ({
        sessions: state.sessions.map((s) =>
          s.id === id ? { ...s, title: newTitle, updatedAt: nowISO() } : s,
        ),
      }));
    },

    // ── State actions ──

    setStreaming: (streaming: boolean) => {
      set({ isStreaming: streaming });
    },

    setConnectionStatus: (status: TransportStatus) => {
      set({ connectionStatus: status });
    },

    setSidebarOpen: (open: boolean) => {
      set({ sidebarOpen: open });
    },
  }));
}
