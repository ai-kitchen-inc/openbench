/** Client for the per-session source family (/chat/sources/{sessionId}). */
import { apiFetch, apiPath } from "../api";
import { parseJsonResponse } from "../shared/apiHelpers";
import type { SourceItem } from "./uploads";

export type SessionFolderResult = { folder: true; count: number; records: SourceItem[] };

export async function listSessionSources(sessionId: string): Promise<SourceItem[]> {
  const response = await apiFetch(apiPath(`/chat/sources/${encodeURIComponent(sessionId)}`));
  return parseJsonResponse<SourceItem[]>(response);
}

export async function addSessionTextSource(
  sessionId: string,
  name: string,
  text: string,
): Promise<SourceItem> {
  const response = await apiFetch(
    apiPath(`/chat/sources/${encodeURIComponent(sessionId)}/text`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, text }),
    },
  );
  return parseJsonResponse<SourceItem>(response);
}

export async function addSessionUrlSource(
  sessionId: string,
  url: string,
): Promise<SourceItem | SessionFolderResult> {
  const response = await apiFetch(
    apiPath(`/chat/sources/${encodeURIComponent(sessionId)}/url`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    },
  );
  return parseJsonResponse<SourceItem | SessionFolderResult>(response);
}

export async function deleteSessionSource(
  sessionId: string,
  sourceId: string,
): Promise<void> {
  const response = await apiFetch(
    apiPath(
      `/chat/sources/${encodeURIComponent(sessionId)}/${encodeURIComponent(sourceId)}`,
    ),
    { method: "DELETE" },
  );
  await parseJsonResponse<{ ok: boolean }>(response);
}
