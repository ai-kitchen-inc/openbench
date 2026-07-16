/** Composer/source upload plumbing (multipart + direct-GCS large uploads),
 * extracted from the legacy general-chat UI. */
import type { Attachment } from "@openbench/chat-ui";
import { apiFetch, apiPath, authHeaders } from "../api";

export const SOURCE_ACCEPT =
  ".xlsx,.xls,.pdf,.epub,.docx,.doc,.pptx,.ppt,.txt,.md,.markdown,.html,.htm,.csv,.json," +
  ".png,.jpg,.jpeg,.webp,.gif,.heic,.heif,.tiff,.tif,.bmp,.svg," +
  ".mp3,.wav,.m4a,.ogg,.aac,.flac," +
  ".mp4,.webm,.mov,.avi";
export const DIRECT_UPLOAD_THRESHOLD_BYTES = 25 * 1024 * 1024;
const DIRECT_UPLOAD_POLL_INTERVAL_MS = 2000;
const DIRECT_UPLOAD_MAX_POLLS = 90;

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
  extractedText?: string;
  metadata?: Record<string, unknown> | null;
};

type DirectUploadInitiateResponse = {
  fileId: string;
  uploadUrl: string;
  method?: string;
  headers?: Record<string, string>;
  source: SourceItem;
};

type DirectUploadStatusResponse = {
  status?: string;
  fileId?: string;
  source: SourceItem;
};

function normalizeDirectUploadStatus(
  payload: DirectUploadStatusResponse | SourceItem,
): DirectUploadStatusResponse {
  if ("source" in payload && payload.source) return payload;
  const source = payload as SourceItem;
  const fileId =
    typeof source.metadata?.fileId === "string" ? source.metadata.fileId : undefined;
  return {
    status: source.status,
    fileId,
    source,
  };
}

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
        throw new Error(
          compact || `${response.status} ${response.statusText}` || "Permintaan gagal",
        );
      }
      throw new Error("Server mengembalikan respons JSON yang tidak valid.");
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

export function sourceToAttachment(source: SourceItem): Attachment | null {
  if (source.status !== "ready") return null;
  const metadata = source.metadata ?? {};
  const imagePath =
    typeof metadata.samSegmentationPath === "string"
      ? metadata.samSegmentationPath
      : typeof metadata.imageSearchPath === "string"
        ? metadata.imageSearchPath
        : undefined;
  return {
    id: source.id,
    type: source.mimeType.startsWith("image/") ? "image" : "file",
    name: source.name,
    url: source.url ?? "",
    mimeType: source.mimeType,
    sizeBytes: source.sizeBytes,
    path: imagePath,
    extractedText: source.extractedText,
    extractedPreview: source.extractedText,
  };
}

function fileIdForSource(source: SourceItem): string | undefined {
  const fileId = source.metadata?.fileId;
  return typeof fileId === "string" && fileId ? fileId : undefined;
}

function sourceToComposerAttachment(source: SourceItem): Attachment {
  const readyAttachment = sourceToAttachment(source);
  if (readyAttachment) return readyAttachment;

  const metadata = source.metadata ?? {};
  const imagePath =
    typeof metadata.samSegmentationPath === "string"
      ? metadata.samSegmentationPath
      : typeof metadata.imageSearchPath === "string"
        ? metadata.imageSearchPath
        : undefined;
  const errorText =
    source.extractedText ||
    source.error ||
    `Pemrosesan sumber ${source.status === "failed" ? "gagal" : "belum selesai"} untuk ${source.name}.`;

  return {
    id: source.id,
    type: source.mimeType.startsWith("image/") ? "image" : "file",
    name: source.name,
    url: source.url ?? "",
    mimeType: source.mimeType,
    sizeBytes: source.sizeBytes,
    path: imagePath,
    extractedText: errorText,
    extractedPreview: errorText,
  };
}

export function sourceKindLabel(source: SourceItem): string {
  if (source.kind === "url") return "WEB";
  if (source.kind === "text") return "TEKS";
  if (source.kind === "spreadsheet") {
    return source.name.toLowerCase().endsWith(".csv") ? "CSV" : "XLSX";
  }
  if (source.kind === "image") return "GAMBAR";
  return source.kind.toUpperCase();
}

export function formatSourceMeta(source: SourceItem): string | null {
  const metadata = source.metadata ?? {};
  if (source.status === "processing") {
    const parseStatus = typeof metadata.parseStatus === "string" ? metadata.parseStatus : "";
    return parseStatus ? `Memproses: ${parseStatus}` : "Memproses sumber";
  }
  if (source.kind === "image") {
    const description = typeof metadata.description === "string" ? metadata.description : "";
    return description || "OCR gambar siap";
  }
  if (source.url) return source.url;
  return null;
}

function xhrUpload(
  method: string,
  url: string,
  body: XMLHttpRequestBodyInit,
  headers: Record<string, string> | undefined,
  onProgress: (fraction: number) => void,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(method, url);
    request.responseType = "json";
    for (const [key, value] of Object.entries(headers ?? {})) {
      if (key.toLowerCase() === "content-length") continue;
      request.setRequestHeader(key, value);
    }
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total);
      }
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response);
        return;
      }
      const detail =
        typeof request.response?.detail === "string"
          ? request.response.detail
          : request.statusText || "Unggahan gagal";
      reject(new Error(detail));
    });
    request.addEventListener("error", () => {
      reject(new Error("Kesalahan jaringan saat mengunggah. Periksa pengaturan HTTPS API dan CORS bucket."));
    });
    request.send(body);
  });
}

async function uploadMultipartSourceFile(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  const form = new FormData();
  form.append("file", file);
  form.append("sessionId", sessionId);
  return (await xhrUpload("POST", apiPath("/chat/upload"), form, await authHeaders(), onProgress)) as SourceItem;
}

async function uploadLargeSourceFile(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  const initiateResponse = await apiFetch(apiPath("/chat/uploads/initiate"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      mimeType: file.type || "application/octet-stream",
      sizeBytes: file.size,
      sessionId,
    }),
  });
  const session = await parseJsonResponse<DirectUploadInitiateResponse>(initiateResponse);
  await xhrUpload(session.method ?? "PUT", session.uploadUrl, file, session.headers, (fraction) => {
    onProgress(Math.min(fraction * 0.95, 0.95));
  });
  onProgress(0.98);
  const completeResponse = await apiFetch(apiPath("/chat/uploads/complete"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fileId: session.fileId, sessionId }),
  });
  const completed = await parseJsonResponse<DirectUploadStatusResponse>(completeResponse);
  onProgress(1);
  return completed.source;
}

function uploadSourceFile(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  if (file.size > DIRECT_UPLOAD_THRESHOLD_BYTES) {
    return uploadLargeSourceFile(file, sessionId, onProgress);
  }
  return uploadMultipartSourceFile(file, sessionId, onProgress);
}

async function fetchUploadStatus(
  fileId: string,
  sessionId: string,
  options: { includeText?: boolean } = {},
): Promise<DirectUploadStatusResponse> {
  const params = new URLSearchParams({ sessionId });
  const includeText = options.includeText ?? false;
  if (includeText) params.set("includeText", "true");
  const response = await apiFetch(
    apiPath(`/chat/uploads/${encodeURIComponent(fileId)}?${params.toString()}`),
  );
  return normalizeDirectUploadStatus(
    await parseJsonResponse<DirectUploadStatusResponse | SourceItem>(response),
  );
}

async function pollUploadedSource(
  fileId: string,
  sessionId: string,
  options: { includeText?: boolean } = {},
): Promise<SourceItem> {
  const includeText = options.includeText ?? false;
  for (let attempt = 0; attempt < DIRECT_UPLOAD_MAX_POLLS; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, DIRECT_UPLOAD_POLL_INTERVAL_MS));
    const status = await fetchUploadStatus(fileId, sessionId, { includeText });
    if (status.source.status === "ready" || status.source.status === "failed") {
      return status.source;
    }
  }
  throw new Error("Unggahan masih diproses. Coba lagi sebentar lagi.");
}

export async function uploadComposerAttachment(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<Attachment> {
  const uploadedSource = await uploadSourceFile(file, sessionId, onProgress);
  const fileId = fileIdForSource(uploadedSource);
  let finalSource = uploadedSource;

  if (fileId) {
    if (uploadedSource.status === "processing") {
      finalSource = await pollUploadedSource(fileId, sessionId, { includeText: true });
    } else {
      finalSource = (await fetchUploadStatus(fileId, sessionId, { includeText: true })).source;
    }
  }

  if (finalSource.status === "processing") {
    throw new Error("Unggahan masih diproses. Coba lagi sebentar lagi.");
  }
  return sourceToComposerAttachment(finalSource);
}
