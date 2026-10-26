/**
 * ObFileCard — OpenBench custom file preview/download card.
 *
 * Uses Lucide-style SVG icons (no emojis).
 */

import { formatFileSize } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveNumber, resolveString } from "../data-binding";

/** Lucide-style SVG icon components for file types. */
function FileTextIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  );
}

function SheetIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <line x1="3" y1="9" x2="21" y2="9" />
      <line x1="3" y1="15" x2="21" y2="15" />
      <line x1="9" y1="3" x2="9" y2="21" />
    </svg>
  );
}

function FileJsonIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <path d="M10 12a1 1 0 0 0-1 1v1a1 1 0 0 1-1 1 1 1 0 0 1 1 1v1a1 1 0 0 0 1 1" />
      <path d="M14 18a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1 1 1 0 0 1-1-1v-1a1 1 0 0 0-1-1" />
    </svg>
  );
}

function ImageIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  );
}

function MusicIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9 18V5l12-2v13" />
      <circle cx="6" cy="18" r="3" />
      <circle cx="18" cy="16" r="3" />
    </svg>
  );
}

function FilmIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18" />
      <line x1="7" y1="2" x2="7" y2="22" />
      <line x1="17" y1="2" x2="17" y2="22" />
      <line x1="2" y1="12" x2="22" y2="12" />
      <line x1="2" y1="7" x2="7" y2="7" />
      <line x1="2" y1="17" x2="7" y2="17" />
      <line x1="17" y1="7" x2="22" y2="7" />
      <line x1="17" y1="17" x2="22" y2="17" />
    </svg>
  );
}

function ArchiveIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="21 8 21 21 3 21 3 8" />
      <rect x="1" y="3" width="22" height="5" />
      <line x1="10" y1="12" x2="14" y2="12" />
    </svg>
  );
}

function PaperclipIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}

function BookIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

type MimeEntry = { prefix: string; icon: () => React.JSX.Element };

const MIME_ICONS: MimeEntry[] = [
  { prefix: "application/pdf", icon: FileTextIcon },
  { prefix: "application/epub+zip", icon: BookIcon },
  { prefix: "text/plain", icon: FileTextIcon },
  { prefix: "text/csv", icon: SheetIcon },
  { prefix: "text/markdown", icon: FileTextIcon },
  { prefix: "application/vnd.openxmlformats-officedocument.spreadsheetml", icon: SheetIcon },
  { prefix: "application/vnd.ms-excel", icon: SheetIcon },
  { prefix: "application/json", icon: FileJsonIcon },
  { prefix: "image/", icon: ImageIcon },
  { prefix: "audio/", icon: MusicIcon },
  { prefix: "video/", icon: FilmIcon },
  { prefix: "application/zip", icon: ArchiveIcon },
  { prefix: "application/gzip", icon: ArchiveIcon },
];

function getFileIcon(mimeType: string): () => React.JSX.Element {
  for (const { prefix, icon } of MIME_ICONS) {
    if (mimeType.startsWith(prefix)) return icon;
  }
  return PaperclipIcon;
}

export const ObFileCard: A2UIComponentRenderer = ({ component, surface }) => {
  const fileName = resolveString(component.fileName, surface);
  const fileUrl = resolveString(component.fileUrl, surface);
  const mimeType = resolveString(component.mimeType ?? "", surface);
  const fileSize = component.fileSize ? resolveNumber(component.fileSize, surface) : undefined;
  const previewUrl = component.previewUrl
    ? resolveString(component.previewUrl, surface)
    : undefined;
  // When the producer sets ``external`` (e.g. Drive webViewLink), open
  // the URL in a new tab as-is instead of triggering a download —
  // the user's authenticated cloud UI handles preview.
  const external = Boolean(component.external);

  const IconComponent = getFileIcon(mimeType);

  return (
    <div
      className="ob-file-card"
      data-component-id={component.id}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "12px",
        padding: "12px 16px",
        border: "1px solid var(--ob-divider-color, rgba(55,53,47,0.09))",
        borderRadius: "8px",
        backgroundColor: "var(--ob-card-bg, #ffffff)",
      }}
    >
      {previewUrl ? (
        <img
          src={previewUrl}
          alt={fileName}
          style={{ width: 40, height: 40, objectFit: "cover", borderRadius: 4 }}
        />
      ) : (
        <span
          style={{ display: "flex", flexShrink: 0, color: "var(--ob-text-secondary, #787774)" }}
        >
          <IconComponent />
        </span>
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
          <div style={{ fontSize: "0.85em", opacity: 0.6 }}>{formatFileSize(fileSize)}</div>
        )}
      </div>
      <a
        href={fileUrl}
        target="_blank"
        rel="noopener noreferrer"
        // Local / backend-proxied files: force the browser to save.
        // External (Drive / cloud viewer): let the cloud UI open in
        // a new tab — no ``download`` attribute so the browser
        // navigates instead of triggering save-as on an HTML page.
        {...(external ? {} : { download: fileName })}
        className="ob-file-card__download"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "4px",
          padding: "6px 12px",
          borderRadius: "4px",
          border: "1px solid var(--ob-divider-color, rgba(55,53,47,0.09))",
          textDecoration: "none",
          fontSize: "0.85em",
          color: "inherit",
        }}
      >
        <DownloadIcon />
        {external ? "Open" : "Download"}
      </a>
    </div>
  );
};
