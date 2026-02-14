/**
 * Main chat hook — composes transport, store, and A2UI processor.
 *
 * Provides the complete chat API: send messages, track streaming,
 * manage sessions, and render A2UI surfaces.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useStore } from "zustand";
import type { ChatStore } from "../core/chat-store";
import { createChatStore } from "../core/chat-store";
import { ChatTransport } from "../core/transport";
import { nowISO } from "../core/utils";
import type {
  A2UIAction,
  A2UISurface,
  Attachment,
  ChatConfig,
  ChatMessage,
  TransportStatus,
} from "../types";
import { useA2UIProcessor } from "./use-a2ui-processor";

export interface UseChatReturn {
  // Messages
  messages: ChatMessage[];
  sendMessage: (content: string, attachments?: Attachment[]) => void;
  isStreaming: boolean;

  // Connection
  connectionStatus: TransportStatus;

  // Sessions
  sessions: ChatStore["sessions"];
  activeSessionId: string | null;
  createSession: () => string;
  switchSession: (id: string) => void;
  deleteSession: (id: string) => void;

  // A2UI surfaces
  surfaces: A2UISurface[];
  sendAction: (action: A2UIAction) => void;

  // UI
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

/**
 * Main hook for chat functionality.
 *
 * ```tsx
 * const { messages, sendMessage, isStreaming } = useChat({
 *   streamUrl: '/chat/stream',
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
  const sidebarOpen = useStore(store, (s) => s.sidebarOpen);

  // Create stable transport instance
  const transportRef = useRef<ChatTransport | null>(null);
  if (!transportRef.current) {
    transportRef.current = new ChatTransport(config);
  }
  const transport = transportRef.current;

  // A2UI processor
  const { processor, surfaces, processMessage, reset: resetProcessor } = useA2UIProcessor();

  // Stable ref for streaming message ID (survives re-renders)
  const streamingMsgRef = useRef<string | null>(null);

  // Handle incoming messages from transport
  const handleMessage = useCallback(
    (data: Record<string, unknown>) => {
      const state = store.getState();

      // Stream envelope messages
      if (data.type === "stream_start") {
        const messageId = data.messageId as string;
        streamingMsgRef.current = messageId;

        // Create placeholder assistant message
        const assistantMsg: ChatMessage = {
          id: messageId,
          role: "assistant",
          content: "",
          timestamp: nowISO(),
          status: "streaming",
        };
        state.addMessage(assistantMsg);
        state.setStreaming(true);
        resetProcessor();
        return;
      }

      if (data.type === "step_start") {
        const messageId = streamingMsgRef.current;
        if (messageId) {
          state.addStep(messageId, data.stepId as string, data.stepName as string);
        }
        return;
      }

      if (data.type === "step_complete") {
        const messageId = streamingMsgRef.current;
        if (messageId) {
          state.completeStep(messageId, data.stepId as string);
        }
        return;
      }

      if (data.type === "stream_end") {
        const messageId = data.messageId as string;
        const rawMeta = data.metadata as Record<string, unknown> | undefined;
        // Extract content fallback (sent by Python engine for text recovery)
        const contentFallback = rawMeta?.content as string | undefined;
        // Build metadata without the content field (it's not real metadata)
        const metadata = rawMeta
          ? (Object.fromEntries(
              Object.entries(rawMeta).filter(([k]) => k !== "content"),
            ) as ChatMessage["metadata"])
          : undefined;
        // Read fresh surfaces from processor (not stale closure)
        const freshSurfaces = processor.getRenderableSurfaces();
        const patch: Partial<ChatMessage> = {
          status: "complete",
          metadata,
          surfaces: freshSurfaces.length > 0 ? [...freshSurfaces] : undefined,
        };
        // Set content fallback if message has no text yet
        const currentMsg = state.messages.find((m) => m.id === messageId);
        if (contentFallback && (!currentMsg?.content || currentMsg.content === "")) {
          patch.content = contentFallback;
        }
        state.updateMessage(messageId, patch);
        state.setStreaming(false);
        streamingMsgRef.current = null;
        return;
      }

      if (data.type === "error") {
        const messageId = data.messageId as string;
        const errorMeta = data.metadata as { error?: string } | undefined;
        state.updateMessage(messageId, {
          status: "error",
          content: errorMeta?.error ?? "An error occurred",
        });
        state.setStreaming(false);
        streamingMsgRef.current = null;
        return;
      }

      // A2UI messages (have "version" field)
      if (data.version === "v0.10") {
        processMessage(data);

        // Read fresh surfaces from processor (not stale closure)
        const currentId = streamingMsgRef.current;
        if (currentId) {
          const freshSurfaces = processor.getRenderableSurfaces();
          state.updateMessage(currentId, {
            surfaces: freshSurfaces.length > 0 ? [...freshSurfaces] : undefined,
          });
        }
        return;
      }

      // Text content chunks (progressive text streaming)
      const currentId = streamingMsgRef.current;
      if (data.type === "text_chunk" && currentId) {
        const chunk = data.content as string;
        const currentMsg = state.messages.find((m) => m.id === currentId);
        if (currentMsg) {
          state.updateMessage(currentId, {
            content: currentMsg.content + chunk,
          });
        }
      }
    },
    [store, processor, processMessage, resetProcessor],
  );

  // Register message listener + status sync + cleanup
  useEffect(() => {
    const unsubMsg = transport.onMessage(handleMessage);
    const unsubStatus = transport.onStatusChange((status) => {
      store.getState().setConnectionStatus(status);
    });

    return () => {
      unsubMsg();
      unsubStatus();
      transport.dispose();
      transportRef.current = null;
    };
  }, [transport, handleMessage, store]);

  // Create initial session if none exists
  useEffect(() => {
    if (store.getState().sessions.length === 0) {
      store.getState().createSession();
    }
  }, [store]);

  // Send message via SSE stream (uploads files first if needed)
  const sendMessage = useCallback(
    (content: string, attachments?: Attachment[]) => {
      const state = store.getState();

      // Show user message immediately with local attachments
      const msg = state.sendMessage(content, attachments);

      // Upload files then stream (async, fire-and-forget)
      (async () => {
        try {
          let serverAttachments: Attachment[] | undefined;

          if (attachments?.length) {
            serverAttachments = await Promise.all(
              attachments.map(async (att) => {
                if (att.file) {
                  const uploaded = await transport.upload(att.file);
                  URL.revokeObjectURL(att.url);
                  return { ...uploaded, file: undefined };
                }
                return att;
              }),
            );
          }

          const payload = {
            type: "message" as const,
            sessionId: state.activeSessionId ?? undefined,
            content,
            attachments: serverAttachments,
          };

          await transport.stream(payload);
        } catch (err) {
          console.error("[useChat] Upload/stream error:", err);
        }
      })();

      return msg;
    },
    [store, transport],
  );

  // Send A2UI action via REST
  const sendAction = useCallback(
    (action: A2UIAction) => {
      transport
        .sendAction({
          type: "action",
          name: action.name,
          surfaceId: action.surfaceId,
          sourceComponentId: action.sourceComponentId,
          timestamp: action.timestamp,
          context: action.context,
        })
        .catch(console.error);
    },
    [transport],
  );

  // Session actions (delegate to store)
  const createSession = useCallback(() => store.getState().createSession(), [store]);
  const switchSession = useCallback((id: string) => store.getState().switchSession(id), [store]);
  const deleteSession = useCallback((id: string) => store.getState().deleteSession(id), [store]);
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
    connectionStatus,
    sessions,
    activeSessionId,
    createSession,
    switchSession,
    deleteSession,
    surfaces,
    sendAction,
    sidebarOpen,
    setSidebarOpen,
  };
}
