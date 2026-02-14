/**
 * ObFileCard — OpenBench custom file preview/download card.
 */

import { formatFileSize } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveNumber, resolveString } from "../data-binding";

const MIME_ICONS: Record<string, string> = {
  "application/pdf": "\u{1F4C4}",
  "text/plain": "\u{1F4DD}",
  "text/csv": "\u{1F4CA}",
  "application/json": "\u{1F4CB}",
  "image/": "\u{1F5BC}",
  "audio/": "\u{1F3B5}",
  "video/": "\u{1F3AC}",
  "application/zip": "\u{1F4E6}",
};

function getFileIcon(mimeType: string): string {
  for (const [prefix, icon] of Object.entries(MIME_ICONS)) {
    if (mimeType.startsWith(prefix)) return icon;
  }
  return "\u{1F4CE}"; // paperclip
}

export const ObFileCard: A2UIComponentRenderer = ({ component, surface }) => {
  const fileName = resolveString(component.fileName, surface);
  const fileUrl = resolveString(component.fileUrl, surface);
  const mimeType = resolveString(component.mimeType ?? "", surface);
  const fileSize = component.fileSize ? resolveNumber(component.fileSize, surface) : undefined;
  const previewUrl = component.previewUrl
    ? resolveString(component.previewUrl, surface)
    : undefined;

  const icon = getFileIcon(mimeType);

  return (
    <div
      className="ob-file-card"
      data-component-id={component.id}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "12px",
        padding: "12px 16px",
        border: "1px solid var(--a2ui-divider-color, #e0e0e0)",
        borderRadius: "8px",
        backgroundColor: "var(--a2ui-card-bg, #ffffff)",
      }}
    >
      {previewUrl ? (
        <img
          src={previewUrl}
          alt={fileName}
          style={{ width: 40, height: 40, objectFit: "cover", borderRadius: 4 }}
        />
      ) : (
        <span style={{ fontSize: 28 }}>{icon}</span>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontWeight: 500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {fileName}
        </div>
        {fileSize != null && (
          <div style={{ fontSize: "0.85em", opacity: 0.7 }}>{formatFileSize(fileSize)}</div>
        )}
      </div>
      <a
        href={fileUrl}
        download={fileName}
        className="ob-file-card__download"
        style={{
          padding: "6px 12px",
          borderRadius: "4px",
          border: "1px solid currentColor",
          textDecoration: "none",
          fontSize: "0.85em",
        }}
      >
        Download
      </a>
    </div>
  );
};
