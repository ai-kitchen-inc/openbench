/**
 * ChatPanel — main chat area with message list and input.
 */

import { ChatInput } from "./ChatInput";
import { useChatContext } from "./ChatProvider";
import { MessageList } from "./MessageList";
import { WelcomeScreen } from "./WelcomeScreen";

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
}

export function ChatPanel({
  className = "",
  placeholder,
  greeting,
  suggestions,
  title,
}: ChatPanelProps) {
  const {
    messages,
    sendMessage,
    isStreaming,
    connectionStatus,
    sendAction,
    sidebarOpen,
    setSidebarOpen,
  } = useChatContext();

  const isEmpty = messages.length === 0;
  const headerTitle = title || (isEmpty ? "New Chat" : "Chat");

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
        </div>
      </div>

      {/* Messages or Welcome */}
      <div className="chat-panel__body">
        {isEmpty ? (
          <WelcomeScreen
            greeting={greeting}
            suggestions={suggestions}
            onSuggestionClick={(s) => sendMessage(s)}
          />
        ) : (
          <MessageList messages={messages} onAction={sendAction} />
        )}
      </div>

      {/* Input */}
      <div className="chat-panel__footer">
        <ChatInput
          onSend={sendMessage}
          disabled={isStreaming}
          placeholder={isStreaming ? "Waiting for response..." : placeholder}
        />
      </div>
    </div>
  );
}
