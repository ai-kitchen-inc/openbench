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
  /**
   * Per-attachment upload progress, keyed by local attachment id,
   * values ``[0, 1]``. When an attachment's id is in the map, the
   * bubble renders a thin progress bar under its name.
   */
  uploadProgress?: Record<string, number>;
}

function formatFileSize(bytes: number | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MessageAttachment({
  attachment,
  uploadFraction,
}: {
  attachment: Attachment;
  uploadFraction?: number;
}) {
  const isImage = attachment.type === "image";
  const isUploading = typeof uploadFraction === "number";

  const progressBar = isUploading ? (
    <div className="chat-attachment__progress" aria-hidden="true">
      <div
        className="chat-attachment__progress-fill"
        style={{ width: `${Math.round((uploadFraction ?? 0) * 100)}%` }}
      />
    </div>
  ) : null;

  if (isImage) {
    return (
      <div className="chat-message__attachment chat-message__attachment--image">
        <img src={attachment.url} alt={attachment.name} className="chat-message__attachment-img" />
        <span className="chat-message__attachment-name">{attachment.name}</span>
        {progressBar}
      </div>
    );
  }

  return (
    <div className="chat-message__attachment chat-message__attachment--file">
      <svg
        aria-hidden="true"
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
        {progressBar}
      </div>
    </div>
  );
}

export function MessageBubble({ message, onAction, uploadProgress }: MessageBubbleProps) {
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
              <MessageAttachment
                key={att.id}
                attachment={att}
                uploadFraction={uploadProgress?.[att.id]}
              />
            ))}
          </div>
        )}

        {/* Text content — always shown, surfaces now only contain rich content */}
        {message.content && (
          <div className="chat-message__text ob-markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
              rehypePlugins={[rehypeRaw, rehypeKatex]}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}

        {/* Streaming indicator (fallback when no steps and no content) */}
        {isStreaming && !hasSteps && !hasContent && <StreamingIndicator />}

        {/* A2UI surfaces. Historical sessions persist a bare
            {surfaceId} reference without the components tree, so skip
            those — SurfaceRenderer would return null anyway, but the
            wrapper div would still take up layout space. */}
        {message.surfaces
          ?.filter((s) => s && typeof (s as { components?: unknown }).components !== "undefined")
          .map((surface) => (
            <div key={surface.surfaceId} className="chat-message__surface">
              <SurfaceRenderer surface={surface} onAction={onAction} />
            </div>
          ))}

        {/* Step indicators — always at the bottom */}
        {hasSteps && (
          <div className="chat-message__steps">
            {message.steps?.map((step) => (
              <StepIndicator key={step.stepId} step={step} />
            ))}
          </div>
        )}

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
