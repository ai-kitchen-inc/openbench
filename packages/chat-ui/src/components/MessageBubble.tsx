/**
 * MessageBubble — renders a single chat message with text and A2UI surfaces.
 */

import { SurfaceRenderer } from "../a2ui/surface-renderer";
import { formatTime } from "../core/utils";
import type { A2UIAction, ChatMessage } from "../types";
import { StepIndicator } from "./StepIndicator";
import { StreamingIndicator } from "./StreamingIndicator";

export interface MessageBubbleProps {
  message: ChatMessage;
  onAction?: (action: A2UIAction) => void;
}

export function MessageBubble({ message, onAction }: MessageBubbleProps) {
  const isStreaming = message.status === "streaming";
  const isError = message.status === "error";
  const hasSteps = message.steps && message.steps.length > 0;
  const hasContent = message.content || message.surfaces?.length;

  return (
    <div
      className={`chat-message chat-message--${message.role} ${isError ? "chat-message--error" : ""}`}
      data-message-id={message.id}
    >
      <div className="chat-message__content">
        {/* Text content */}
        {message.content && <div className="chat-message__text">{message.content}</div>}

        {/* Step indicators */}
        {hasSteps && (
          <div className="chat-message__steps">
            {message.steps?.map((step) => (
              <StepIndicator key={step.stepId} step={step} />
            ))}
          </div>
        )}

        {/* Streaming indicator (fallback when no steps and no content) */}
        {isStreaming && !hasSteps && !hasContent && <StreamingIndicator />}

        {/* A2UI surfaces */}
        {message.surfaces?.map((surface) => (
          <div key={surface.surfaceId} className="chat-message__surface">
            <SurfaceRenderer surface={surface} onAction={onAction} />
          </div>
        ))}

        {/* Metadata footer */}
        <div className="chat-message__meta">
          <span className="chat-message__time">{formatTime(message.timestamp)}</span>
          {message.metadata?.model && (
            <span className="chat-message__model">{message.metadata.model}</span>
          )}
          {isError && <span className="chat-message__error-badge">Error</span>}
        </div>
      </div>
    </div>
  );
}
