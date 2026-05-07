/**
 * ChatPanel — main chat area with message list and input.
 */

import { ChatInput } from "./ChatInput";
import { useChatContext } from "./ChatProvider";
import { MessageList } from "./MessageList";
import { WelcomeScreen } from "./WelcomeScreen";
import type { Attachment } from "../types";

export interface ChatPanelProps {
  /** Additional CSS class. */
  className?: string;
  /** Placeholder text for the input. */
  placeholder?: string;
  /** Welcome screen greeting. */
  greeting?: string;
  /** Suggestion prompts for empty state. */
  suggestions?: string[];
  /** Title displayed in the header (default: "New Chat"). */
  title?: string;
  /** Extra content rendered in the header-right area (e.g. theme toggle). */
  headerRight?: React.ReactNode;
  /** Attachments that should be included with every sent message. */
  persistentAttachments?: Attachment[];
}

export function ChatPanel({
  className = "",
  placeholder,
  greeting,
  suggestions,
  title,
  headerRight,
  persistentAttachments,
}: ChatPanelProps) {
  const {
    messages,
    sendMessage,
    retryMessage,
    isStreaming,
    isLoadingSession,
    uploadProgress,
    connectionStatus,
    sendAction,
    sidebarOpen,
    setSidebarOpen,
  } = useChatContext();

  const isEmpty = messages.length === 0;
  const headerTitle = title || (isEmpty ? "New Chat" : "Chat");
  const sendWithPersistentAttachments = (content: string, attachments?: Attachment[]) => {
    const merged = [...(attachments ?? []), ...(persistentAttachments ?? [])];
    sendMessage(content, merged.length > 0 ? merged : undefined);
  };

  return (
    <div className={`chat-panel ${className}`}>
      {/* Header */}
      <div className="chat-panel__header">
        <div className="chat-panel__header-left">
          {!sidebarOpen && (
            <button
              className="chat-panel__sidebar-toggle"
              onClick={() => setSidebarOpen(true)}
              type="button"
              aria-label="Open sidebar"
            >
              <svg
                aria-hidden="true"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <line x1="9" y1="3" x2="9" y2="21" />
              </svg>
            </button>
          )}
          <span className="chat-panel__title">{headerTitle}</span>
        </div>
        <div className="chat-panel__header-right">
          {connectionStatus === "error" && (
            <div className="chat-panel__status chat-panel__status--error">
              <svg
                aria-hidden="true"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span>Connection error</span>
            </div>
          )}
          {headerRight}
        </div>
      </div>

      {/* Messages or Welcome */}
      <div className="chat-panel__body">
        {isLoadingSession && isEmpty ? (
          <SessionLoading />
        ) : isEmpty ? (
          <WelcomeScreen
            greeting={greeting}
            suggestions={suggestions}
            onSuggestionClick={(s) => sendWithPersistentAttachments(s)}
          />
        ) : (
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            onAction={sendAction}
            uploadProgress={uploadProgress}
            onRetry={retryMessage}
          />
        )}
      </div>

      {/* Input */}
      <div className="chat-panel__footer">
        <ChatInput onSend={sendWithPersistentAttachments} placeholder={placeholder} />
      </div>
    </div>
  );
}

/**
 * Three shimmering message-shaped placeholders. Shown while a session
 * is hydrating from the server so the user knows something is in
 * flight instead of staring at an empty panel.
 */
function SessionLoading() {
  return (
    <div className="chat-loading" role="status" aria-live="polite" aria-busy="true">
      <span className="chat-loading__sr">Loading chat history…</span>
      <div className="chat-loading__bubble chat-loading__bubble--user">
        <div className="chat-loading__line" style={{ width: "42%" }} />
      </div>
      <div className="chat-loading__bubble chat-loading__bubble--assistant">
        <div className="chat-loading__line" style={{ width: "85%" }} />
        <div className="chat-loading__line" style={{ width: "70%" }} />
        <div className="chat-loading__line" style={{ width: "45%" }} />
      </div>
      <div className="chat-loading__bubble chat-loading__bubble--user">
        <div className="chat-loading__line" style={{ width: "55%" }} />
      </div>
    </div>
  );
}
