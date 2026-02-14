/**
 * AttachmentPreview — shows file/media attachments before sending.
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
          <div className="chat-attachment-preview__icon">{getAttachmentIcon(att.type)}</div>
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
            &times;
          </button>
        </div>
      ))}
    </div>
  );
}

function getAttachmentIcon(type: Attachment["type"]): string {
  switch (type) {
    case "image":
      return "\u{1F5BC}";
    case "audio":
      return "\u{1F3B5}";
    case "video":
      return "\u{1F3AC}";
    default:
      return "\u{1F4CE}";
  }
}
