/**
 * MessageList — scrollable message history with auto-scroll.
 */

import { useEffect, useRef } from "react";
import type { A2UIAction, ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";

export interface MessageListProps {
  messages: ChatMessage[];
  onAction?: (action: A2UIAction) => void;
}

export function MessageList({ messages, onAction }: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (endRef.current && typeof endRef.current.scrollIntoView === "function") {
      endRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length]);

  return (
    <div className="chat-message-list" ref={containerRef}>
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} onAction={onAction} />
      ))}
      <div ref={endRef} />
    </div>
  );
}
