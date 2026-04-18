/**
 * Main chat hook — composes StreamManager, transport, and store.
 *
 * Provides the complete chat API: send messages, track streaming,
 * manage sessions, and render A2UI surfaces.
 *
 * Supports parallel streaming: multiple messages can stream concurrently.
 * Each stream gets its own HttpAgent subscription and A2UI processor.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useStore } from "zustand";
import type { ChatStore } from "../core/chat-store";
import { createChatStore } from "../core/chat-store";
import { StreamManager } from "../core/stream-manager";
import { AGUITransport } from "../core/transport";
import { generateId, nowISO } from "../core/utils";
import type {
  A2UIAction,
  A2UISurface,
  Attachment,
  ChatConfig,
  ChatMessage,
  TransportStatus,
} from "../types";

export interface UseChatReturn {
  // Messages
  messages: ChatMessage[];
  sendMessage: (content: string, attachments?: Attachment[]) => void;
  isStreaming: boolean;
  /**
   * True while the active session is being hydrated from the server
   * (switchSession fetches the full message list on demand). UI can
   * surface a spinner to avoid "nothing happened" perception.
   */
  isLoadingSession: boolean;
  /**
   * True while at least one upload is in flight. Use to disable the
   * send button or show a top-level indicator.
   */
  isUploading: boolean;
  /**
   * Per-attachment upload progress map, keyed by local attachment id.
   * Values are ``[0, 1]``. Entries disappear when the upload
   * completes or fails.
   */
  uploadProgress: Record<string, number>;

  // Connection
  connectionStatus: TransportStatus;

  // Sessions
  sessions: ChatStore["sessions"];
  activeSessionId: string | null;
  createSession: () => string;
  switchSession: (id: string) => void;
  deleteSession: (id: string) => void;
  renameSession: (id: string, newTitle: string) => void;

  // A2UI surfaces (kept for backward compat — per-message surfaces are in message.surfaces)
  surfaces: A2UISurface[];
  sendAction: (action: A2UIAction) => Promise<void>;

  // UI
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

/**
 * Main hook for chat functionality.
 *
 * ```tsx
 * const { messages, sendMessage, isStreaming } = useChat({
 *   streamUrl: '/awp',
 * });
 * ```
 */
export function useChat(config: ChatConfig): UseChatReturn {
  // Create a stable store instance
  const store = useMemo(() => createChatStore(), []);

  // Select state from store
  const messages = useStore(store, (s) => s.messages);
  const isStreaming = useStore(store, (s) => s.isStreaming);
  const sessions = useStore(store, (s) => s.sessions);
  const activeSessionId = useStore(store, (s) => s.activeSessionId);
  const loadingSessionIds = useStore(store, (s) => s.loadingSessionIds);
  const isLoadingSession = activeSessionId !== null && !!loadingSessionIds[activeSessionId];
  const uploadProgress = useStore(store, (s) => s.uploadProgress);
  const isUploading = Object.keys(uploadProgress).length > 0;
  const sidebarOpen = useStore(store, (s) => s.sidebarOpen);

  // Create stable transport instance (for upload + sendAction + status)
  const transportRef = useRef<AGUITransport | null>(null);
  if (!transportRef.current) {
    transportRef.current = new AGUITransport(config);
  }
  const transport = transportRef.current;

  // Create stable StreamManager instance
  const streamManagerRef = useRef<StreamManager | null>(null);
  if (!streamManagerRef.current) {
    streamManagerRef.current = new StreamManager({
      streamUrl: config.streamUrl,
      store,
      maxConcurrent: config.maxConcurrentStreams ?? 3,
      getAuthToken: config.getAuthToken,
    });
  }
  const streamManager = streamManagerRef.current;

  // Sync transport status to store
  useEffect(() => {
    const unsubStatus = transport.onStatusChange((status) => {
      store.getState().setConnectionStatus(status);
    });

    return () => {
      unsubStatus();
      streamManager.dispose();
      transport.dispose();
      transportRef.current = null;
      streamManagerRef.current = null;
    };
  }, [transport, streamManager, store]);

  // Hydrate sessions from the backend on mount.
  // If the server returns any sessions, merge them into the store and
  // skip auto-creating a new one. If the backend has no session store
  // (empty list or 404), fall back to the original "create one if
  // empty" behavior so the app works without persistence.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const summaries = await transport.listSessions();
      if (cancelled) return;
      if (summaries.length > 0) {
        const placeholders = summaries.map((s) => ({
          id: s.sessionId,
          title: s.title,
          messages: [],
          createdAt: s.createdAt,
          updatedAt: s.updatedAt,
        }));
        store.getState().hydrateSessions(placeholders);
      } else if (store.getState().sessions.length === 0) {
        store.getState().createSession();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [store, transport]);

  // Send message — creates independent parallel stream via StreamManager
  const sendMessage = useCallback(
    (content: string, attachments?: Attachment[]) => {
      const state = store.getState();

      // Show user message immediately with local attachments
      const msg = state.sendMessage(content, attachments);

      // Create placeholder assistant message
      const assistantId = generateId();
      const sessionId = state.activeSessionId;
      if (!sessionId) return msg;

      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        timestamp: nowISO(),
        status: "streaming",
      };
      store.getState().addMessageToSession(sessionId, assistantMsg);

      // Upload files then start parallel stream (async, fire-and-forget)
      (async () => {
        try {
          let serverAttachments: Attachment[] | undefined;

          if (attachments?.length) {
            serverAttachments = await Promise.all(
              attachments.map(async (att) => {
                if (att.file) {
                  // Seed a 0% entry so the UI paints a progress bar
                  // immediately — otherwise a fast XHR on localhost
                  // can complete before the first progress event
                  // fires and the bar never renders.
                  store.getState().setUploadProgress(att.id, 0);
                  const localFile = att.file;
                  try {
                    const uploaded = await transport.upload(localFile, {
                      onProgress: (frac) =>
                        store.getState().setUploadProgress(att.id, frac),
                    });
                    URL.revokeObjectURL(att.url);
                    config.onUploadSuccess?.(att.id, uploaded);
                    return { ...uploaded, file: undefined };
                  } catch (err) {
                    config.onUploadError?.(localFile, err);
                    throw err;
                  } finally {
                    store.getState().clearUploadProgress(att.id);
                  }
                }
                return att;
              }),
            );
          }

          // Start independent stream — does NOT cancel other active streams
          await streamManager.startStream(sessionId, assistantId, content, serverAttachments);
        } catch (err) {
          console.error("[useChat] Upload/stream error:", err);
        }
      })();

      return msg;
    },
    [store, transport, streamManager],
  );

  // Send A2UI action — routes response to correct message's processor
  const sendAction = useCallback(
    async (action: A2UIAction) => {
      // Find surface to check sendDataModel flag
      const state = store.getState();
      const allMessages = state.messages;
      let surface: A2UISurface | undefined;
      for (const msg of allMessages) {
        surface = msg.surfaces?.find((s) => s.surfaceId === action.surfaceId);
        if (surface) break;
      }

      const payload: {
        name: string;
        surfaceId: string;
        sourceComponentId: string;
        timestamp: string;
        context: Record<string, unknown>;
        dataModel?: Record<string, unknown>;
        threadId?: string;
      } = {
        name: action.name,
        surfaceId: action.surfaceId,
        sourceComponentId: action.sourceComponentId,
        timestamp: action.timestamp,
        context: action.context,
      };

      // Attach full dataModel when surface has sendDataModel flag
      if (surface?.sendDataModel) {
        payload.dataModel = surface.dataModel;
      }

      // Attach threadId from active session
      if (state.activeSessionId) {
        payload.threadId = state.activeSessionId;
      }

      const messages = await transport.sendAction(payload);

      // Route A2UI response to the processor that owns the surface
      if (messages.length > 0) {
        streamManager.processActionResponse(action.surfaceId, messages);
      }
    },
    [transport, streamManager, store],
  );

  // Session actions (delegate to store)
  const createSession = useCallback(() => store.getState().createSession(), [store]);

  // Switch session; if the session is a hydration placeholder with no
  // messages yet, lazy-load its full content from the server.
  const switchSession = useCallback(
    (id: string) => {
      store.getState().switchSession(id);
      const session = store.getState().sessions.find((s) => s.id === id);
      if (session && session.messages.length === 0) {
        (async () => {
          store.getState().setSessionLoading(id, true);
          try {
            const loaded = await transport.loadSession(id);
            if (loaded) {
              store.getState().hydrateSessionMessages(id, loaded.messages);
            }
          } catch (err) {
            console.error("[useChat] loadSession failed:", err);
          } finally {
            store.getState().setSessionLoading(id, false);
          }
        })();
      }
    },
    [store, transport],
  );

  // Delete session both locally and on the server (fire-and-forget);
  // a server failure does not block the UI — the user will see it
  // come back on the next reload, which is acceptable.
  const deleteSession = useCallback(
    (id: string) => {
      streamManager.removeProcessor(id);
      store.getState().deleteSession(id);
      transport.deleteSession(id).catch((err) => {
        console.error("[useChat] deleteSession server sync failed:", err);
      });
    },
    [store, streamManager, transport],
  );

  const renameSession = useCallback(
    (id: string, newTitle: string) => store.getState().renameSession(id, newTitle),
    [store],
  );
  const setSidebarOpen = useCallback(
    (open: boolean) => store.getState().setSidebarOpen(open),
    [store],
  );

  // Read connectionStatus from store
  const connectionStatus = useStore(store, (s) => s.connectionStatus);

  return {
    messages,
    sendMessage,
    isStreaming,
    isLoadingSession,
    isUploading,
    uploadProgress,
    connectionStatus,
    sessions,
    activeSessionId,
    createSession,
    switchSession,
    deleteSession,
    renameSession,
    surfaces: [], // Deprecated at hook level — use message.surfaces instead
    sendAction,
    sidebarOpen,
    setSidebarOpen,
  };
}
