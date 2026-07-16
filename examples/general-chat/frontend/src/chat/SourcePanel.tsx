/** Per-session source list (view + delete), extracted from the legacy
 * general-chat UI with Bahasa labels. */
import type { Attachment } from "@openbench/chat-ui";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiPath } from "../api";
import { useToast } from "../Toast";
import {
  formatSourceMeta,
  parseJsonResponse,
  readErrorMessage,
  sourceKindLabel,
  sourceToAttachment,
  type SourceItem,
} from "./uploads";

export function SourcePanel({
  sessionId,
  onAttachmentsChange,
  refreshToken = 0,
}: {
  sessionId: string | null;
  onAttachmentsChange: (attachments: Attachment[]) => void;
  refreshToken?: number;
}) {
  const toast = useToast();
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [isLoadingSources, setIsLoadingSources] = useState(false);
  const [isMutating, setIsMutating] = useState(false);

  const loadSources = useCallback(
    async (targetSessionId: string): Promise<SourceItem[]> => {
      setIsLoadingSources(true);
      try {
        const response = await apiFetch(apiPath(`/chat/sources/${encodeURIComponent(targetSessionId)}`));
        const items = await parseJsonResponse<SourceItem[]>(response);
        setSources(items);
        return items;
      } catch (error) {
        toast.show(`Gagal memuat sumber: ${readErrorMessage(error)}`, "error");
        setSources([]);
        return [];
      } finally {
        setIsLoadingSources(false);
      }
    },
    [toast],
  );

  useEffect(() => {
    if (!sessionId) {
      setSources([]);
      onAttachmentsChange([]);
      return;
    }
    void loadSources(sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken, sessionId]);

  useEffect(() => {
    onAttachmentsChange(sources.map(sourceToAttachment).filter(Boolean) as Attachment[]);
  }, [onAttachmentsChange, sources]);

  const handleDeleteSource = useCallback(
    async (sourceId: string) => {
      if (!sessionId) return;
      setIsMutating(true);
      try {
        const response = await apiFetch(
          apiPath(`/chat/sources/${encodeURIComponent(sessionId)}/${encodeURIComponent(sourceId)}`),
          { method: "DELETE" },
        );
        await parseJsonResponse<{ ok: boolean }>(response);
        await loadSources(sessionId);
      } catch (error) {
        toast.show(`Gagal menghapus sumber: ${readErrorMessage(error)}`, "error");
      } finally {
        setIsMutating(false);
      }
    },
    [loadSources, sessionId, toast],
  );

  return (
    <div className="source-panel">
      <div className="source-panel__header">
        <div className="source-panel__title">Sumber</div>
      </div>

      {isLoadingSources ? (
        <div className="source-panel__state">Memuat sumber...</div>
      ) : sources.length === 0 ? (
        <div className="source-panel__empty">
          <div className="source-panel__empty-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M14 2H6a2 2 0 0 0-2 2v16l4-3 4 3 4-3 4 3V8z" />
              <path d="M14 2v6h6" />
            </svg>
          </div>
          <div>Tambahkan berkas, situs web, gambar, atau teks sebagai konteks opsional.</div>
        </div>
      ) : (
        <div className="source-panel__list">
          {sources.map((source) => {
            const meta = formatSourceMeta(source);
            return (
              <div
                key={source.id}
                className={`source-panel__item${source.status === "failed" ? " source-panel__item--failed" : ""}${source.status === "processing" ? " source-panel__item--processing" : ""}`}
              >
                <div className="source-panel__item-badge">{sourceKindLabel(source)}</div>
                <div className="source-panel__item-main">
                  <div className="source-panel__item-name">{source.name}</div>
                  {meta && <div className="source-panel__item-meta">{meta}</div>}
                  {source.status === "failed" && (
                    <div className="source-panel__item-error">{source.error ?? "Pemrosesan sumber gagal"}</div>
                  )}
                  {source.status === "processing" && (
                    <div className="source-panel__item-meta">Antre untuk diproses</div>
                  )}
                </div>
                <button
                  type="button"
                  className="source-panel__item-remove"
                  aria-label={`Hapus ${source.name}`}
                  disabled={isMutating}
                  onClick={() => void handleDeleteSource(source.id)}
                >
                  x
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
