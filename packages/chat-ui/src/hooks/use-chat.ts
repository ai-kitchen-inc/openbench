/**
 * Main chat hook — composes AG-UI transport, store, and A2UI processor.
 *
 * Provides the complete chat API: send messages, track streaming,
 * manage sessions, and render A2UI surfaces.
 */

import type { BaseEvent } from "@ag-ui/core";
import { EventType } from "@ag-ui/core";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useStore } from "zustand";
import type { ChatStore } from "../core/chat-store";
import { createChatStore } from "../core/chat-store";
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
  const sidebarOpen = useStore(store, (s) => s.sidebarOpen);

  // Create stable transport instance
  const transportRef = useRef<AGUITransport | null>(null);
  if (!transportRef.current) {
    transportRef.current = new AGUITransport(config);
  }
  const transport = transportRef.current;

  // A2UI processor
  const { processor, surfaces, processMessage, reset: resetProcessor } = useA2UIProcessor();

  // Stable ref for streaming message ID (survives re-renders)
  const streamingMsgRef = useRef<string | null>(null);

  // Handle incoming AG-UI events from transport
  const handleEvent = useCallback(
    (event: BaseEvent) => {
      const state = store.getState();
      // Cast to Record for safe property access (BaseEvent is Zod-inferred)
      const raw = event as unknown as Record<string, unknown>;
      const eventType = raw.type as string;

      if (eventType === EventType.RUN_STARTED) {
        const messageId = generateId();
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

      if (eventType === EventType.STEP_STARTED) {
        const messageId = streamingMsgRef.current;
        if (messageId) {
          const stepName = raw.stepName as string;
          state.addStep(messageId, generateId(), stepName);
        }
        return;
      }

      if (eventType === EventType.STEP_FINISHED) {
        const messageId = streamingMsgRef.current;
        if (messageId) {
          // Complete the most recent active step
          const msg = state.messages.find((m) => m.id === messageId);
          const activeStep = msg?.steps?.find((s) => s.status === "active");
          if (activeStep) {
            state.completeStep(messageId, activeStep.stepId);
          }
        }
        return;
      }

      if (eventType === EventType.CUSTOM) {
        const name = raw.name as string;
        if (name === "a2ui") {
          // A2UI message — process through A2UI processor
          processMessage(raw.value as Record<string, unknown>);

          // Update surfaces on the streaming message
          const currentId = streamingMsgRef.current;
          if (currentId) {
            const freshSurfaces = processor.getRenderableSurfaces();
            state.updateMessage(currentId, {
              surfaces: freshSurfaces.length > 0 ? [...freshSurfaces] : undefined,
            });
          }
        }
        return;
      }

      if (eventType === EventType.RUN_FINISHED) {
        const messageId = streamingMsgRef.current;
        if (!messageId) return;

        const result = raw.result as
          | { content?: string; metadata?: Record<string, unknown> }
          | undefined;
        const contentFallback = result?.content;
        const metadata = result?.metadata as ChatMessage["metadata"] | undefined;

        // Read fresh surfaces from processor
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

      if (eventType === EventType.RUN_ERROR) {
        const messageId = streamingMsgRef.current;
        const errorMessage = (raw.message as string) ?? "An error occurred";

        if (messageId) {
          state.updateMessage(messageId, {
            status: "error",
            content: errorMessage,
          });
        }

        state.setStreaming(false);
        streamingMsgRef.current = null;
        return;
      }

      // Text content chunks (progressive text streaming)
      if (eventType === EventType.TEXT_MESSAGE_CONTENT) {
        const currentId = streamingMsgRef.current;
        if (currentId) {
          const delta = (raw.delta as string) ?? "";
          const currentMsg = state.messages.find((m) => m.id === currentId);
          if (currentMsg) {
            state.updateMessage(currentId, {
              content: currentMsg.content + delta,
            });
          }
        }
      }
    },
    [store, processor, processMessage, resetProcessor],
  );

  // Register event listener + status sync + cleanup
  useEffect(() => {
    const unsubEvent = transport.onEvent(handleEvent);
    const unsubStatus = transport.onStatusChange((status) => {
      store.getState().setConnectionStatus(status);
    });

    return () => {
      unsubEvent();
      unsubStatus();
      transport.dispose();
      transportRef.current = null;
    };
  }, [transport, handleEvent, store]);

  // Create initial session if none exists
  useEffect(() => {
    if (store.getState().sessions.length === 0) {
      store.getState().createSession();
    }
  }, [store]);

  // Send message via AG-UI stream (uploads files first if needed)
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

          await transport.run(content, state.activeSessionId ?? undefined, serverAttachments);
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
