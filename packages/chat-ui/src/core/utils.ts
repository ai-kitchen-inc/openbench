/**
 * Utility helpers for @openbench/chat-ui.
 *
 * Pure functions with no React dependency.
 */

/**
 * Generate a unique ID with optional prefix.
 */
export function generateId(prefix = ""): string {
  const random = Math.random().toString(36).substring(2, 10);
  const timestamp = Date.now().toString(36);
  return prefix ? `${prefix}-${timestamp}${random}` : `${timestamp}${random}`;
}

/**
 * Format a file size in bytes to a human-readable string.
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const size = bytes / 1024 ** i;
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/**
 * Format a timestamp string or Date to a time display (e.g., "2:30 PM").
 */
export function formatTime(timestamp: string | Date): string {
  const date = typeof timestamp === "string" ? new Date(timestamp) : timestamp;
  return date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Format a timestamp to a relative time (e.g., "2 min ago", "Yesterday").
 */
export function formatRelativeTime(timestamp: string | Date): string {
  const date = typeof timestamp === "string" ? new Date(timestamp) : timestamp;
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffSec < 60) return "Just now";
  if (diffMin < 60) return `${diffMin} min ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay === 1) return "Yesterday";
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

/**
 * Check if a value is a DataBinding object ({path: string}).
 */
export function isDataBinding(value: unknown): value is { path: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "path" in value &&
    typeof (value as Record<string, unknown>).path === "string" &&
    !("call" in value)
  );
}

/**
 * Check if a value is a FunctionCall object ({call: string}).
 */
export function isFunctionCall(
  value: unknown,
): value is { call: string; args?: Record<string, unknown> } {
  return (
    typeof value === "object" &&
    value !== null &&
    "call" in value &&
    typeof (value as Record<string, unknown>).call === "string"
  );
}

/**
 * Get the current ISO 8601 timestamp string.
 */
export function nowISO(): string {
  return new Date().toISOString();
}
