/**
 * Zustand store for chat state management.
 *
 * Manages sessions, messages, streaming state, and connection status.
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

  // UI
  sidebarOpen: boolean;
}

export interface ChatActions {
  // Message actions
  sendMessage: (content: string, attachments?: Attachment[]) => ChatMessage;
  addMessage: (message: ChatMessage) => void;
  updateMessage: (id: string, patch: Partial<ChatMessage>) => void;
  appendSurface: (messageId: string, surface: A2UISurface) => void;
  addStep: (messageId: string, stepId: string, stepName: string) => void;
  completeStep: (messageId: string, stepId: string) => void;

  // Session actions
  createSession: () => string;
  switchSession: (id: string) => void;
  deleteSession: (id: string) => void;

  // State actions
  setStreaming: (streaming: boolean) => void;
  setConnectionStatus: (status: TransportStatus) => void;
  setSidebarOpen: (open: boolean) => void;
}

export type ChatStore = ChatState & ChatActions;

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
    sidebarOpen: true,

    // ── Message actions ──

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
      const { sessions } = get();
      const session = sessions.find((s) => s.id === id);
      if (session) {
        set({
          activeSessionId: id,
          messages: [...session.messages],
          isStreaming: false,
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
