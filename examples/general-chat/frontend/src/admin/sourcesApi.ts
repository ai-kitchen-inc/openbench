/** Admin client for the global shared sources (/admin/shared-sources). */
import { apiPath, authHeaders } from "../api";
import {
  addSharedTextSource,
  addSharedUrlSource,
  deleteSharedSource,
  listSharedSources,
  parseJsonResponse,
  readErrorMessage,
  type SharedSource,
} from "../account/api";

export type SourceItem = SharedSource;

export { parseJsonResponse, readErrorMessage };

export async function listSources(): Promise<SourceItem[]> {
  return listSharedSources();
}

export async function addTextSource(name: string, text: string): Promise<SourceItem> {
  return addSharedTextSource(name, text);
}

export async function addUrlSource(url: string): Promise<SourceItem> {
  return addSharedUrlSource(url);
}

export async function deleteSource(sourceId: string): Promise<void> {
  await deleteSharedSource(sourceId);
}

/** Multipart upload of a global shared source with progress reporting. */
export function uploadSourceFile(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  return new Promise((resolve, reject) => {
    void (async () => {
      const form = new FormData();
      form.append("file", file);
      const request = new XMLHttpRequest();
      request.open("POST", apiPath("/admin/shared-sources/upload"));
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
            : request.statusText || "Unggahan gagal";
        reject(new Error(detail));
      });
      request.addEventListener("error", () => {
        reject(new Error("Kesalahan jaringan saat mengunggah."));
      });
      request.send(form);
    })();
  });
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
  if (source.status === "processing") return "Memproses sumber";
  if (source.url) return source.url;
  return null;
}
