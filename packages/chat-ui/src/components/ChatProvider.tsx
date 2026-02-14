/**
 * ChatProvider — React context provider for chat state.
 *
 * Wraps children with the full chat API via context.
 * Components inside can use `useChatContext()` to access chat state.
 */

import { createContext, useContext } from "react";
import { useChat } from "../hooks/use-chat";
import type { UseChatReturn } from "../hooks/use-chat";
import type { ChatConfig } from "../types";

const ChatContext = createContext<UseChatReturn | null>(null);

export interface ChatProviderProps {
  /** Transport and theme configuration. */
  config: ChatConfig;
  children: React.ReactNode;
}

/**
 * Provides chat state and actions to all child components.
 *
 * ```tsx
 * <ChatProvider config={{ streamUrl: '/chat/stream' }}>
 *   <ChatPanel />
 * </ChatProvider>
 * ```
 */
export function ChatProvider({ config, children }: ChatProviderProps) {
  const chat = useChat(config);

  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>;
}

/**
 * Access the chat context. Must be used inside a `<ChatProvider>`.
 */
export function useChatContext(): UseChatReturn {
  const ctx = useContext(ChatContext);
  if (!ctx) {
    throw new Error("useChatContext must be used inside a <ChatProvider>");
  }
  return ctx;
}
