/** Copy-paste snippets shown in the Agen panel once an embed key exists. */
import { API_BASE_URL } from "../api";

/** Origin external callers should use: the configured backend URL when
 * the SPA is served separately, otherwise the page's own origin (single
 * origin deploy). */
export function embedOrigin(): string {
  return API_BASE_URL || window.location.origin;
}

export function embedPageUrl(origin: string, agentId: string, key: string): string {
  return `${origin}/embed/${encodeURIComponent(agentId)}?key=${encodeURIComponent(key)}`;
}

export function iframeSnippet(origin: string, agentId: string, key: string): string {
  return [
    `<iframe`,
    `  src="${embedPageUrl(origin, agentId, key)}"`,
    `  title="Chat"`,
    `  style="width: 100%; height: 640px; border: 0;"`,
    `  allow="clipboard-write"`,
    `></iframe>`,
  ].join("\n");
}

export function curlSnippet(origin: string, agentId: string, key: string): string {
  const body = JSON.stringify({
    threadId: "t-1",
    runId: "r-1",
    messages: [{ id: "m-1", role: "user", content: "Halo" }],
  });
  return [
    `curl -N -X POST ${origin}/agents/${encodeURIComponent(agentId)}/awp \\`,
    `  -H "Authorization: Bearer ${key}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '${body}'`,
  ].join("\n");
}

/** Show only the edges of a secret so it can be recognised, not copied. */
export function maskKey(key: string): string {
  if (key.length <= 8) return "•".repeat(key.length);
  return `${key.slice(0, 4)}…${key.slice(-4)}`;
}
