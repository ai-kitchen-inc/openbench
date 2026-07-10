import { apiFetch, apiPath, authHeaders } from "../api";
import { CONTROLLED_THREAD_ID } from "../constants";

export type SourceItem = {
  id: string;
  sessionId: string;
  name: string;
  kind: string;
  mimeType: string;
  status: "ready" | "failed" | "processing";
  error: string | null;
  sizeBytes: number;
  createdAt: string;
  url: string | null;
  metadata?: Record<string, unknown> | null;
};

export function readErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export async function parseJsonResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let payload: Record<string, unknown> = {};
  if (text) {
    try {
      payload = JSON.parse(text) as Record<string, unknown>;
    } catch {
      const compact = text.replace(/\s+/g, " ").trim();
      if (!response.ok) {
        throw new Error(compact || `${response.status} ${response.statusText}`);
      }
      throw new Error("Server returned an invalid JSON response.");
    }
  }
  if (!response.ok) {
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : typeof payload?.error === "string"
          ? payload.error
          : `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }
  return payload as T;
}

export async function listSources(): Promise<SourceItem[]> {
  const response = await apiFetch(apiPath(`/chat/sources/${CONTROLLED_THREAD_ID}`));
  return parseJsonResponse<SourceItem[]>(response);
}

export async function addTextSource(name: string, text: string): Promise<SourceItem> {
  const response = await apiFetch(apiPath(`/chat/sources/${CONTROLLED_THREAD_ID}/text`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, text }),
  });
  return parseJsonResponse<SourceItem>(response);
}

export async function addUrlSource(url: string): Promise<SourceItem> {
  const response = await apiFetch(apiPath(`/chat/sources/${CONTROLLED_THREAD_ID}/url`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  return parseJsonResponse<SourceItem>(response);
}

export async function deleteSource(sourceId: string): Promise<void> {
  const response = await apiFetch(
    apiPath(`/chat/sources/${CONTROLLED_THREAD_ID}/${encodeURIComponent(sourceId)}`),
    { method: "DELETE" },
  );
  await parseJsonResponse<{ ok: boolean }>(response);
}

/** Multipart upload into the curated thread (local-first: no GCS path). */
export function uploadSourceFile(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  return new Promise((resolve, reject) => {
    void (async () => {
      const form = new FormData();
      form.append("file", file);
      form.append("sessionId", CONTROLLED_THREAD_ID);
      const request = new XMLHttpRequest();
      request.open("POST", apiPath("/chat/upload"));
      request.responseType = "json";
      for (const [key, value] of Object.entries(await authHeaders())) {
        request.setRequestHeader(key, value);
      }
      request.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable && event.total > 0) {
          onProgress(event.loaded / event.total);
        }
      });
      request.addEventListener("load", () => {
        if (request.status >= 200 && request.status < 300) {
          resolve(request.response as SourceItem);
          return;
        }
        const detail =
          typeof request.response?.detail === "string"
            ? request.response.detail
            : request.statusText || "Upload failed";
        reject(new Error(detail));
      });
      request.addEventListener("error", () => {
        reject(new Error("Network error while uploading."));
      });
      request.send(form);
    })();
  });
}

export function sourceKindLabel(source: SourceItem): string {
  if (source.kind === "url") return "WEB";
  if (source.kind === "text") return "TEXT";
  if (source.kind === "spreadsheet") {
    return source.name.toLowerCase().endsWith(".csv") ? "CSV" : "XLSX";
  }
  if (source.kind === "image") return "IMAGE";
  return source.kind.toUpperCase();
}

export function formatSourceMeta(source: SourceItem): string | null {
  const metadata = source.metadata ?? {};
  if (source.status === "processing") {
    const parseStatus = typeof metadata.parseStatus === "string" ? metadata.parseStatus : "";
    return parseStatus ? `Processing: ${parseStatus}` : "Processing source";
  }
  if (source.url) return source.url;
  return null;
}
