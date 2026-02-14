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
}

export function ChatPanel({ className = "", placeholder, greeting, suggestions }: ChatPanelProps) {
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
  const isDisconnected = connectionStatus === "disconnected" || connectionStatus === "error";

  return (
    <div className={`chat-panel ${className}`}>
      {/* Header */}
      <div className="chat-panel__header">
        {!sidebarOpen && (
          <button
            className="chat-panel__sidebar-toggle"
            onClick={() => setSidebarOpen(true)}
            type="button"
            aria-label="Open sidebar"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        )}
        <div className="chat-panel__status">
          <span className={`chat-panel__status-dot chat-panel__status-dot--${connectionStatus}`} />
          <span className="chat-panel__status-text">
            {connectionStatus === "connected"
              ? "Connected"
              : connectionStatus === "connecting"
                ? "Connecting..."
                : connectionStatus === "error"
                  ? "Connection error"
                  : "Disconnected"}
          </span>
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
          disabled={isStreaming || isDisconnected}
          placeholder={
            isDisconnected
              ? "Reconnecting..."
              : isStreaming
                ? "Waiting for response..."
                : placeholder
          }
        />
      </div>
    </div>
  );
}
