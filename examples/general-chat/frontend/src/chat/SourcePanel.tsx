/** Per-session source panel (file/text/URL/Drive + delete), built on the
 * shared SourceManager with Bahasa labels. */
import type { Attachment } from "@openbench/chat-ui";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useToast } from "../Toast";
import { readErrorMessage } from "../shared/apiHelpers";
import { type ManagedSource } from "../sources/model";
import { SourceManager, type SourceManagerApi } from "../sources/SourceManager";
import {
  connectDrive,
  disconnectDrive,
  fetchDriveStatus,
  type DriveStatus,
} from "./driveApi";
import {
  addSessionTextSource,
  addSessionUrlSource,
  deleteSessionSource,
  listSessionSources,
} from "./sessionSourcesApi";
import { sourceToAttachment, uploadSourceFile, type SourceItem } from "./uploads";

export function SourcePanel({
  sessionId,
  onAttachmentsChange,
  refreshToken = 0,
}: {
  sessionId: string | null;
  onAttachmentsChange: (attachments: Attachment[]) => void;
  refreshToken?: number;
}) {
  const sourcesApi = useMemo<SourceManagerApi | null>(() => {
    if (!sessionId) return null;
    return {
      list: () => listSessionSources(sessionId),
      uploadFile: (file, onProgress) => uploadSourceFile(file, sessionId, onProgress),
      addText: (name, text) => addSessionTextSource(sessionId, name, text),
      addUrl: (url) => addSessionUrlSource(sessionId, url),
      remove: (sourceId) => deleteSessionSource(sessionId, sourceId),
    };
  }, [sessionId]);

  // Grounds the composer: ready sources ride along as attachments.
  const handleSourcesChange = useCallback(
    (sources: ManagedSource[]) => {
      onAttachmentsChange(
        (sources as SourceItem[]).map(sourceToAttachment).filter(Boolean) as Attachment[],
      );
    },
    [onAttachmentsChange],
  );

  // A stable placeholder API keeps SourceManager mountable pre-session;
  // `disabled` prevents it from ever being called.
  const placeholderApi = useMemo<SourceManagerApi>(
    () => ({ list: async () => [], remove: async () => {} }),
    [],
  );

  return (
    <div className="source-panel">
      <div className="source-panel__header">
        <div className="source-panel__title">Sumber</div>
      </div>

      <SourceManager
        key={sessionId ?? "no-session"}
        api={sourcesApi ?? placeholderApi}
        variant="panel"
        disabled={!sessionId}
        disabledHint="Mulai percakapan untuk menambah sumber."
        urlPlaceholder="https://... atau tautan Google Drive/Docs"
        emptyState={
          <div className="source-panel__empty">
            <div className="source-panel__empty-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M14 2H6a2 2 0 0 0-2 2v16l4-3 4 3 4-3 4 3V8z" />
                <path d="M14 2v6h6" />
              </svg>
            </div>
            <div>Tambahkan berkas, situs web, gambar, atau teks sebagai konteks opsional.</div>
          </div>
        }
        onSourcesChange={handleSourcesChange}
        refreshToken={refreshToken}
      />

      <DriveConnectCard />
    </div>
  );
}

function DriveConnectCard() {
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
        disabled={isBusy}
        onClick={() => void (status.connected ? handleDisconnect() : handleConnect())}
      >
        {status.connected ? "Putuskan" : "Hubungkan"}
      </button>
    </div>
  );
}
