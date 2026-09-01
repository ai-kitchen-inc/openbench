/** Unified source shape + presentation helpers. Every backend source family
 * (session, shared/global, group, agent) serializes the same SourceRecord, so
 * the UI works off one structural type instead of four drifting copies. */

export type ManagedSource = {
  id: string;
  name: string;
  kind?: string;
  status?: "ready" | "failed" | "processing" | string;
  error?: string | null;
  url?: string | null;
  mimeType?: string;
  sizeBytes?: number;
  createdAt?: string;
  sessionId?: string;
  extractedText?: string;
  textPreview?: string;
  textTruncated?: boolean;
  metadata?: Record<string, unknown> | null;
};

export function sourceKindLabel(source: Pick<ManagedSource, "kind" | "name">): string {
  const kind = source.kind ?? "";
  if (kind === "url") return "WEB";
  if (kind === "text") return "TEKS";
  if (kind === "spreadsheet") {
    return source.name.toLowerCase().endsWith(".csv") ? "CSV" : "XLSX";
  }
  if (kind === "image") return "GAMBAR";
  return kind ? kind.toUpperCase() : "SUMBER";
}

export function formatSourceMeta(source: ManagedSource): string | null {
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
