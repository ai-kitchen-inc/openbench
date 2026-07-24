/** Per-session source list (view + add URL/Drive + delete), extracted
 * from the legacy general-chat UI with Bahasa labels. */
import type { Attachment } from "@openbench/chat-ui";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch, apiPath } from "../api";
import { useToast } from "../Toast";
import {
  connectDrive,
  disconnectDrive,
  fetchDriveStatus,
  type DriveStatus,
} from "./driveApi";
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
  const [showUrlForm, setShowUrlForm] = useState(false);
  const [urlValue, setUrlValue] = useState("");

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

  const handleAddUrl = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      const url = urlValue.trim();
      if (!sessionId || !url) return;
      setIsMutating(true);
      try {
        const response = await apiFetch(
          apiPath(`/chat/sources/${encodeURIComponent(sessionId)}/url`),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
          },
        );
        const record = await parseJsonResponse<SourceItem>(response);
        if (record.status === "failed") {
          toast.show(record.error ?? "Pemrosesan sumber gagal", "error");
        } else {
          toast.show(`Sumber ditambahkan: ${record.name}`, "success");
          setUrlValue("");
          setShowUrlForm(false);
        }
        await loadSources(sessionId);
      } catch (error) {
        toast.show(`Gagal menambah sumber: ${readErrorMessage(error)}`, "error");
      } finally {
        setIsMutating(false);
      }
    },
    [loadSources, sessionId, toast, urlValue],
  );

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
        <button
          type="button"
          className="source-panel__add-btn"
          disabled={isMutating || !sessionId}
          onClick={() => setShowUrlForm((value) => !value)}
        >
          Tambah URL
        </button>
      </div>

      {!sessionId && showUrlForm && (
        <div className="source-panel__state">Mulai percakapan untuk menambah sumber.</div>
      )}
      {sessionId && showUrlForm && (
        <form className="source-panel__inline" onSubmit={(event) => void handleAddUrl(event)}>
          <input
            type="url"
            className="source-panel__input"
            placeholder="https://... atau tautan Google Drive/Docs"
            value={urlValue}
            onChange={(event) => setUrlValue(event.target.value)}
            required
          />
          <button type="submit" className="source-panel__mini-btn" disabled={isMutating}>
            Tambah
          </button>
        </form>
      )}

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

      <DriveConnectCard disabled={isMutating} />
    </div>
  );
}

function DriveConnectCard({ disabled }: { disabled: boolean }) {
  const toast = useToast();
  const [status, setStatus] = useState<DriveStatus | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchDriveStatus()
      .then((value) => {
        if (!cancelled) setStatus(value);
      })
      .catch(() => {
        if (!cancelled) setStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!status?.configured) return null;

  const handleConnect = async () => {
    setIsBusy(true);
    try {
      const { authorizeUrl } = await connectDrive();
      window.location.assign(authorizeUrl);
    } catch (error) {
      toast.show(`Gagal menghubungkan Drive: ${readErrorMessage(error)}`, "error");
      setIsBusy(false);
    }
  };

  const handleDisconnect = async () => {
    setIsBusy(true);
    try {
      await disconnectDrive();
      setStatus({ ...status, connected: false, email: null });
      toast.show("Google Drive diputuskan", "success");
    } catch (error) {
      toast.show(`Gagal memutuskan Drive: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="source-panel__drive">
      <span className="source-panel__drive-icon" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <line x1="22" y1="12" x2="2" y2="12" />
          <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
          <line x1="6" y1="16" x2="6.01" y2="16" />
          <line x1="10" y1="16" x2="10.01" y2="16" />
        </svg>
      </span>
      <span className="source-panel__drive-text">
        {status.connected
          ? `Google Drive terhubung${status.email ? ` sebagai ${status.email}` : ""}`
          : "Hubungkan Google Drive untuk menambahkan berkas privat lewat tautan."}
      </span>
      <button
        type="button"
        className="source-panel__mini-btn"
        disabled={disabled || isBusy}
        onClick={() => void (status.connected ? handleDisconnect() : handleConnect())}
      >
        {status.connected ? "Putuskan" : "Hubungkan"}
      </button>
    </div>
  );
}
