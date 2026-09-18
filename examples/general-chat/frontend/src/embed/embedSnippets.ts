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

/** Password-style mask: one bullet per character, nothing recognisable. */
export function maskSecret(secret: string): string {
  return "•".repeat(secret.length);
}

/** Replace every occurrence of the secret (raw or URL-encoded) in a
 * snippet with its mask, so hidden mode never shows it anywhere. */
export function redactSecret(text: string, secret: string): string {
  if (!secret) return text;
  const mask = maskSecret(secret);
  return text.split(encodeURIComponent(secret)).join(mask).split(secret).join(mask);
}
