/**
 * MessageBubble — renders a single chat message with text, attachments, and A2UI surfaces.
 */

import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { SurfaceRenderer } from "../a2ui/surface-renderer";
import { formatTime } from "../core/utils";
import type { A2UIAction, Attachment, ChatMessage } from "../types";
import { StepIndicator } from "./StepIndicator";
import { StreamingIndicator } from "./StreamingIndicator";

export interface MessageBubbleProps {
  message: ChatMessage;
  onAction?: (action: A2UIAction) => void;
}

function formatFileSize(bytes: number | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MessageAttachment({ attachment }: { attachment: Attachment }) {
  const isImage = attachment.type === "image";

  if (isImage) {
    return (
      <div className="chat-message__attachment chat-message__attachment--image">
        <img src={attachment.url} alt={attachment.name} className="chat-message__attachment-img" />
        <span className="chat-message__attachment-name">{attachment.name}</span>
      </div>
    );
  }

  return (
    <div className="chat-message__attachment chat-message__attachment--file">
      <svg
        className="chat-message__attachment-icon"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      >
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
      <div className="chat-message__attachment-info">
        <span className="chat-message__attachment-name">{attachment.name}</span>
        {attachment.sizeBytes != null && (
          <span className="chat-message__attachment-size">
            {formatFileSize(attachment.sizeBytes)}
          </span>
        )}
      </div>
    </div>
  );
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
        {/* User attachments */}
        {message.attachments && message.attachments.length > 0 && (
          <div className="chat-message__attachments">
            {message.attachments.map((att) => (
              <MessageAttachment key={att.id} attachment={att} />
            ))}
          </div>
        )}

        {/* Text content — always shown, surfaces now only contain rich content */}
        {message.content && (
          <div className="chat-message__text ob-markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeRaw, rehypeKatex]}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}

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
