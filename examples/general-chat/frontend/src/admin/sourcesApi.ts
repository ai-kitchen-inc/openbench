/** Admin client for the global shared sources (/admin/shared-sources). */
import { apiPath, authHeaders } from "../api";
import {
  addSharedTextSource,
  addSharedUrlSource,
  deleteSharedSource,
  listSharedSources,
  type SharedSource,
} from "../account/api";
import { parseJsonResponse, readErrorMessage, xhrUpload } from "../shared/apiHelpers";
import { formatSourceMeta, sourceKindLabel } from "../sources/model";

export type SourceItem = SharedSource;

export { parseJsonResponse, readErrorMessage };
export { formatSourceMeta, sourceKindLabel };

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
export async function uploadSourceFile(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  const form = new FormData();
  form.append("file", file);
  return (await xhrUpload(
    "POST",
    apiPath("/admin/shared-sources/upload"),
    form,
    await authHeaders(),
    onProgress,
  )) as SourceItem;
}
