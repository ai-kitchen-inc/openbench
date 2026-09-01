/** Shared add-file / paste-text / add-URL source manager. One component for
 * every source family (global shared, group, agent, session) — the endpoints
 * differ per family, so callers pass a SourceManagerApi adapter and only the
 * handlers that exist for that family render as buttons. */
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { XIcon } from "../brand/icons";
import { useToast } from "../Toast";
import { SOURCE_ACCEPT } from "../chat/uploads";
import { readErrorMessage } from "../shared/apiHelpers";
import { formatSourceMeta, sourceKindLabel, type ManagedSource } from "./model";

const PROCESSING_POLL_MS = 2500;

export type FolderAddResult = { folder: true; count: number; records: ManagedSource[] };

export type SourceManagerApi = {
  list(): Promise<ManagedSource[]>;
  uploadFile?(file: File, onProgress: (fraction: number) => void): Promise<ManagedSource>;
  addText?(name: string, text: string): Promise<ManagedSource>;
  /** Drive folder links may expand into several records. */
  addUrl?(url: string): Promise<ManagedSource | FolderAddResult>;
  remove(sourceId: string): Promise<void>;
};

type AddMode = "none" | "text" | "url";

export function SourceManager({
  api,
  variant = "section",
  accept = SOURCE_ACCEPT,
  disabled = false,
  disabledHint,
  emptyState,
  urlPlaceholder = "https://contoh.go.id/halaman-yang-diambil",
  onSourcesChange,
  refreshToken = 0,
}: {
  /** Memoize in the caller — a new object per render retriggers the loader. */
  api: SourceManagerApi;
  variant?: "section" | "panel";
  accept?: string;
  disabled?: boolean;
  disabledHint?: string;
  emptyState?: ReactNode;
  urlPlaceholder?: string;
  onSourcesChange?: (sources: ManagedSource[]) => void;
  refreshToken?: number | string;
}) {
  const { show: showToast } = useToast();
  const [sources, setSources] = useState<ManagedSource[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isMutating, setIsMutating] = useState(false);
  const [addMode, setAddMode] = useState<AddMode>("none");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const items = await api.list();
      setSources(items);
      onSourcesChange?.(items);
    } catch (error) {
      showToast(`Gagal memuat sumber: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsLoading(false);
    }
  }, [api, onSourcesChange, showToast]);

  useEffect(() => {
    if (disabled) {
      setSources([]);
      setIsLoading(false);
      onSourcesChange?.([]);
      return;
    }
    setIsLoading(true);
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disabled, refresh, refreshToken]);

  // Poll while any source is still parsing so status badges settle on
  // ready/failed without a manual refresh.
  const hasProcessing = sources.some((source) => source.status === "processing");
  useEffect(() => {
    if (!hasProcessing || disabled) return;
    const timer = setInterval(() => void refresh(), PROCESSING_POLL_MS);
    return () => clearInterval(timer);
  }, [disabled, hasProcessing, refresh]);

  const runMutation = useCallback(
    async (mutation: () => Promise<void>) => {
      setIsMutating(true);
      try {
        await mutation();
        await refresh();
      } catch (error) {
        showToast(readErrorMessage(error), "error");
      } finally {
        setIsMutating(false);
      }
    },
    [refresh, showToast],
  );

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      const upload = api.uploadFile;
      if (!upload || !files || files.length === 0) return;
      setIsMutating(true);
      try {
        for (const file of Array.from(files)) {
          setUploadProgress(0);
          const uploaded = await upload(file, setUploadProgress);
          if (uploaded?.status === "failed") {
            showToast(uploaded.error ?? `Pemrosesan gagal: ${file.name}`, "error");
          } else {
            showToast(`Berhasil diunggah: ${file.name}`, "success");
          }
        }
        await refresh();
      } catch (error) {
        showToast(`Gagal mengunggah: ${readErrorMessage(error)}`, "error");
      } finally {
        setUploadProgress(null);
        setIsMutating(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    },
    [api, refresh, showToast],
  );

  const handleAddUrl = useCallback(
    (url: string) =>
      runMutation(async () => {
        const payload = await api.addUrl!(url);
        if ("records" in payload) {
          const okCount = payload.records.filter((r) => r.status !== "failed").length;
          if (okCount === 0) {
            showToast(payload.records[0]?.error ?? "Pemrosesan folder gagal", "error");
            return;
          }
          showToast(`${okCount} sumber ditambahkan dari folder`, "success");
        } else if (payload.status === "failed") {
          showToast(payload.error ?? "Pemrosesan sumber gagal", "error");
          return;
        } else {
          showToast(`Sumber ditambahkan: ${payload.name}`, "success");
        }
        setAddMode("none");
      }),
    [api, runMutation, showToast],
  );

  const panel = variant === "panel";
  const buttonClass = panel ? "source-panel__add-btn" : "panel-button";
  const primaryButtonClass = panel
    ? "source-panel__add-btn"
    : "panel-button panel-button--primary";
  const rowClass = panel ? "source-panel__item" : "source-row";
  const rowPrefix = panel ? "source-panel__item" : "source-row";
  const listClass = panel ? "source-panel__list" : "sources-list";
  const stateClass = panel ? "source-panel__state" : "sources-list__empty";

  return (
    <div className={`source-manager${panel ? " source-manager--panel" : ""}`}>
      <div className={panel ? "source-panel__actions" : "sources-add"}>
        {api.uploadFile && (
          <button
            type="button"
            className={primaryButtonClass}
            onClick={() => fileInputRef.current?.click()}
            disabled={isMutating || disabled}
          >
            {uploadProgress !== null
              ? `Mengunggah ${Math.round(uploadProgress * 100)}%`
              : "Unggah Dokumen"}
          </button>
        )}
        {api.addText && (
          <button
            type="button"
            className={buttonClass}
            onClick={() => setAddMode(addMode === "text" ? "none" : "text")}
            disabled={isMutating || disabled}
          >
            Tempel Teks
          </button>
        )}
        {api.addUrl && (
          <button
            type="button"
            className={buttonClass}
            onClick={() => setAddMode(addMode === "url" ? "none" : "url")}
            disabled={isMutating || disabled}
          >
            Tambah URL
          </button>
        )}
        {api.uploadFile && (
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={accept}
            style={{ display: "none" }}
            onChange={(event) => void handleFiles(event.target.files)}
          />
        )}
      </div>

      {disabled && disabledHint && <div className={stateClass}>{disabledHint}</div>}

      {!disabled && addMode === "text" && api.addText && (
        <TextSourceForm
          disabled={isMutating}
          buttonClass={primaryButtonClass}
          onSubmit={(name, text) =>
            void runMutation(async () => {
              const added = await api.addText!(name, text);
              if (added?.status === "failed") {
                showToast(added.error ?? "Pemrosesan sumber gagal", "error");
                return;
              }
              setAddMode("none");
            })
          }
        />
      )}
      {!disabled && addMode === "url" && api.addUrl && (
        <UrlSourceForm
          disabled={isMutating}
          buttonClass={primaryButtonClass}
          placeholder={urlPlaceholder}
          onSubmit={(url) => void handleAddUrl(url)}
        />
      )}

      {disabled ? null : isLoading ? (
        <div className={stateClass}>Memuat sumber...</div>
      ) : sources.length === 0 ? (
        (emptyState ?? <div className={stateClass}>Belum ada sumber.</div>)
      ) : (
        <div className={listClass}>
          {sources.map((source) => {
            const meta = formatSourceMeta(source);
            const failed = source.status === "failed";
            const processing = source.status === "processing";
            return (
              <div
                key={source.id}
                className={`${rowClass}${failed ? ` ${rowClass}--failed` : ""}${
                  panel && processing ? ` ${rowClass}--processing` : ""
                }`}
              >
                <div className={panel ? `${rowPrefix}-badge` : `${rowPrefix}__badge`}>
                  {sourceKindLabel(source)}
                </div>
                <div className={panel ? `${rowPrefix}-main` : `${rowPrefix}__main`}>
                  <div className={panel ? `${rowPrefix}-name` : `${rowPrefix}__name`}>
                    {source.name}
                  </div>
                  {meta && (
                    <div className={panel ? `${rowPrefix}-meta` : `${rowPrefix}__meta`}>
                      {meta}
                    </div>
                  )}
                  {failed && (
                    <div className={panel ? `${rowPrefix}-error` : `${rowPrefix}__error`}>
                      {source.error ?? "Pemrosesan sumber gagal"}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className={panel ? `${rowPrefix}-remove` : `${rowPrefix}__remove`}
                  aria-label={`Hapus ${source.name}`}
                  disabled={isMutating}
                  onClick={() => void runMutation(() => api.remove(source.id))}
                >
                  <XIcon size={14} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function TextSourceForm({
  disabled,
  buttonClass,
  onSubmit,
}: {
  disabled: boolean;
  buttonClass: string;
  onSubmit: (name: string, text: string) => void;
}) {
  const [name, setName] = useState("");
  const [text, setText] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!text.trim()) return;
    onSubmit(name.trim() || "Teks tempel", text);
  };

  return (
    <form className="sources-form" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Nama sumber (mis. FAQ Layanan Publik)"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <textarea
        placeholder="Tempel teks sumber yang dapat ditanyakan pengguna..."
        value={text}
        onChange={(event) => setText(event.target.value)}
        required
      />
      <div className="sources-form__row">
        <button type="submit" className={buttonClass} disabled={disabled}>
          Tambah Sumber Teks
        </button>
      </div>
    </form>
  );
}

function UrlSourceForm({
  disabled,
  buttonClass,
  placeholder,
  onSubmit,
}: {
  disabled: boolean;
  buttonClass: string;
  placeholder: string;
  onSubmit: (url: string) => void;
}) {
  const [url, setUrl] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!url.trim()) return;
    onSubmit(url.trim());
  };

  return (
    <form className="sources-form" onSubmit={handleSubmit}>
      <input
        type="url"
        placeholder={placeholder}
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        required
      />
      <div className="sources-form__row">
        <button type="submit" className={buttonClass} disabled={disabled}>
          Tambah Sumber URL
        </button>
      </div>
    </form>
  );
}
