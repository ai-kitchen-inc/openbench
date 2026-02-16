/**
 * AttachmentPreview — shows file/media attachments before sending.
 *
 * Uses Lucide-style SVG icons (no emojis).
 */

import { formatFileSize } from "../core/utils";
import type { Attachment } from "../types";

export interface AttachmentPreviewProps {
  attachments: Attachment[];
  onRemove: (id: string) => void;
}

export function AttachmentPreview({ attachments, onRemove }: AttachmentPreviewProps) {
  if (attachments.length === 0) return null;

  return (
    <div className="chat-attachment-preview">
      {attachments.map((att) => (
        <div key={att.id} className="chat-attachment-preview__item">
          <div className="chat-attachment-preview__icon">
            <AttachmentIcon type={att.type} />
          </div>
          <div className="chat-attachment-preview__info">
            <span className="chat-attachment-preview__name">{att.name}</span>
            {att.sizeBytes != null && (
              <span className="chat-attachment-preview__size">{formatFileSize(att.sizeBytes)}</span>
            )}
          </div>
          <button
            className="chat-attachment-preview__remove"
            onClick={() => onRemove(att.id)}
            type="button"
            aria-label={`Remove ${att.name}`}
          >
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
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}

function AttachmentIcon({ type }: { type: Attachment["type"] }) {
  const size = 18;
  const props = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  switch (type) {
    case "image":
      return (
        <svg aria-hidden="true" {...props}>
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <polyline points="21 15 16 10 5 21" />
        </svg>
      );
    case "audio":
      return (
        <svg aria-hidden="true" {...props}>
          <path d="M9 18V5l12-2v13" />
          <circle cx="6" cy="18" r="3" />
          <circle cx="18" cy="16" r="3" />
        </svg>
      );
    case "video":
      return (
        <svg aria-hidden="true" {...props}>
          <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18" />
          <line x1="7" y1="2" x2="7" y2="22" />
          <line x1="17" y1="2" x2="17" y2="22" />
          <line x1="2" y1="12" x2="22" y2="12" />
        </svg>
      );
    default:
      return (
        <svg aria-hidden="true" {...props}>
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
        </svg>
      );
  }
}
