/** Shared REST-response and upload plumbing used by every API client module
 * (chat uploads, account/admin clients, functions). Single source of truth —
 * the per-module copies were drifting. */

/** Mirrors MAX_ATTACHMENTS in openbench.chat.transport.validation. Enforced
 * in the composer so a big batch is rejected with a readable message instead
 * of a 422 after every file has already been uploaded. */
export const MAX_ATTACHMENTS_PER_MESSAGE = 50;

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
    const coded = translateErrorDetail(payload?.detail);
    const detail =
      coded ??
      (typeof payload?.detail === "string"
        ? payload.detail
        : typeof payload?.error === "string"
          ? payload.error
          : `${response.status} ${response.statusText}`);
    throw new Error(detail);
  }
  return payload as T;
}

/** Turn a structured `{code, ...}` error detail into Indonesian copy.
 * The transport returns a code rather than a sentence so the wording
 * lives here with the rest of the UI strings. */
function translateErrorDetail(detail: unknown): string | null {
  if (!detail || typeof detail !== "object") return null;
  const { code, max } = detail as { code?: unknown; max?: unknown };
  if (code === "too_many_attachments") {
    const limit = typeof max === "number" ? max : MAX_ATTACHMENTS_PER_MESSAGE;
    return `Terlalu banyak berkas dalam satu pesan (maksimum ${limit}). Kirim sebagian dulu.`;
  }
  return null;
}

/** XHR-based upload with progress reporting (fetch has no upload progress). */
export function xhrUpload(
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
      reject(
        new Error(
          "Kesalahan jaringan saat mengunggah. Periksa pengaturan HTTPS API dan CORS bucket.",
        ),
      );
    });
    request.send(body);
  });
}
