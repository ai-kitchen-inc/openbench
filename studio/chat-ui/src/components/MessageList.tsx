/**
 * MessageList — scrollable message history with auto-scroll.
 *
 * Scrolls the parent container (chat-panel__body) to bottom when content
 * changes during streaming. Uses instant scroll during streaming to avoid
 * animation cancellation on rapid deltas.
 */

import { useEffect, useRef } from "react";
import type { A2UIAction, ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";

export interface MessageListProps {
  messages: ChatMessage[];
  isStreaming?: boolean;
  onAction?: (action: A2UIAction) => void;
  /** Per-attachment upload progress; forwarded to each MessageBubble. */
  uploadProgress?: Record<string, number>;
}

export function MessageList({
  messages,
  isStreaming,
  onAction,
  uploadProgress,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Track content changes for scroll trigger.
  const lastMsg = messages[messages.length - 1];
  const scrollDep = `${messages.length}-${lastMsg?.content?.length ?? 0}-${lastMsg?.surfaces?.length ?? 0}`;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // The scrollable parent is chat-panel__body (overflow-y: auto).
    const scrollParent = el.parentElement;
    if (!scrollParent) return;

    if (isStreaming) {
      // Instant scroll during streaming — no animation to cancel on rapid deltas
      scrollParent.scrollTop = scrollParent.scrollHeight;
    } else if (typeof scrollParent.scrollTo === "function") {
      // Smooth scroll for new messages / completion
      scrollParent.scrollTo({
        top: scrollParent.scrollHeight,
        behavior: "smooth",
      });
    } else {
      // Fallback (e.g. jsdom) — instant scroll
      scrollParent.scrollTop = scrollParent.scrollHeight;
    }
  }, [scrollDep, isStreaming]);

  return (
    <div className="chat-message-list" ref={containerRef}>
      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          message={msg}
          onAction={onAction}
          uploadProgress={uploadProgress}
        />
      ))}
    </div>
  );
}
