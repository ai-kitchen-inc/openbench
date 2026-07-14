import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useToast } from "../Toast";
import { SOURCE_ACCEPT } from "../constants";
import {
  addTextSource,
  addUrlSource,
  deleteSource,
  formatSourceMeta,
  listSources,
  readErrorMessage,
  sourceKindLabel,
  uploadSourceFile,
  type SourceItem,
} from "./sourcesApi";

const PROCESSING_POLL_MS = 2500;

type AddMode = "none" | "text" | "url";

export function SourcesSection() {
  // Only the stable show() callback — depending on the whole context object
  // (which changes with every toast) would re-create refresh and retrigger
  // the load effect in a feedback loop.
  const { show: showToast } = useToast();
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isMutating, setIsMutating] = useState(false);
  const [addMode, setAddMode] = useState<AddMode>("none");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setSources(await listSources());
    } catch (error) {
      showToast(`Could not load sources: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll while any source is still parsing so status badges settle on
  // ready/failed without a manual refresh.
  const hasProcessing = sources.some((source) => source.status === "processing");
  useEffect(() => {
    if (!hasProcessing) return;
    const timer = setInterval(() => void refresh(), PROCESSING_POLL_MS);
    return () => clearInterval(timer);
  }, [hasProcessing, refresh]);

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
      if (!files || files.length === 0) return;
      setIsMutating(true);
      try {
        for (const file of Array.from(files)) {
          setUploadProgress(0);
          await uploadSourceFile(file, setUploadProgress);
          showToast(`Uploaded: ${file.name}`, "success");
        }
        await refresh();
      } catch (error) {
        showToast(`Upload failed: ${readErrorMessage(error)}`, "error");
      } finally {
        setUploadProgress(null);
        setIsMutating(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    },
    [refresh, showToast],
  );

  return (
    <section className="panel-section" aria-label="Knowledge base sources">
      <div className="panel-section__header">
        <div>
          <div className="panel-section__title">
            <SourcesIcon />
            Sources
          </div>
          <div className="panel-section__subtitle">
            Everything users can ask about. The assistant answers only from these sources and
            cites them by name.
          </div>
        </div>
      </div>
      <div className="panel-section__body">
        <div className="sources-add">
          <button
            type="button"
            className="panel-button panel-button--primary"
            onClick={() => fileInputRef.current?.click()}
            disabled={isMutating}
          >
            {uploadProgress !== null
              ? `Uploading ${Math.round(uploadProgress * 100)}%`
              : "Upload document"}
          </button>
          <button
            type="button"
            className="panel-button"
            onClick={() => setAddMode(addMode === "text" ? "none" : "text")}
            disabled={isMutating}
          >
            Paste text
          </button>
          <button
            type="button"
            className="panel-button"
            onClick={() => setAddMode(addMode === "url" ? "none" : "url")}
            disabled={isMutating}
          >
            Add URL
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={SOURCE_ACCEPT}
            style={{ display: "none" }}
            onChange={(event) => void handleFiles(event.target.files)}
          />
        </div>

        {addMode === "text" && (
          <TextSourceForm
            disabled={isMutating}
            onSubmit={(name, text) =>
              void runMutation(async () => {
                await addTextSource(name, text);
                setAddMode("none");
              })
            }
          />
        )}
        {addMode === "url" && (
          <UrlSourceForm
            disabled={isMutating}
            onSubmit={(url) =>
              void runMutation(async () => {
                await addUrlSource(url);
                setAddMode("none");
              })
            }
          />
        )}

        {isLoading ? (
          <div className="sources-list__empty">Loading sources...</div>
        ) : sources.length === 0 ? (
          <div className="panel-empty">
            <span className="panel-empty__icon">
              <EmptyIcon />
            </span>
            <div className="panel-empty__title">No sources yet</div>
            <div className="panel-empty__hint">
              Users cannot get answers until you add at least one source. Upload a document,
              paste text, or add a URL.
            </div>
          </div>
        ) : (
          <div className="sources-list">
            {sources.map((source) => (
              <div
                key={source.id}
                className={`source-row${source.status === "failed" ? " source-row--failed" : ""}`}
              >
                <div className="source-row__badge">{sourceKindLabel(source)}</div>
                <div className="source-row__main">
                  <div className="source-row__name">{source.name}</div>
                  {formatSourceMeta(source) && (
                    <div className="source-row__meta">{formatSourceMeta(source)}</div>
                  )}
                  {source.status === "failed" && (
                    <div className="source-row__error">
                      {source.error ?? "Source processing failed"}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className="source-row__remove"
                  aria-label={`Remove ${source.name}`}
                  disabled={isMutating}
                  onClick={() => void runMutation(() => deleteSource(source.id))}
                >
                  <svg
                    aria-hidden="true"
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  >
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function TextSourceForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (name: string, text: string) => void;
}) {
  const [name, setName] = useState("");
  const [text, setText] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!text.trim()) return;
    onSubmit(name.trim() || "Pasted text", text);
  };

  return (
    <form className="sources-form" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Source name (e.g. Company FAQ)"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <textarea
        placeholder="Paste the source text users can ask about..."
        value={text}
        onChange={(event) => setText(event.target.value)}
        required
      />
      <div className="sources-form__row">
        <button type="submit" className="panel-button panel-button--primary" disabled={disabled}>
          Add text source
        </button>
      </div>
    </form>
  );
}

function UrlSourceForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
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
        placeholder="https://example.com/page-to-ingest"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        required
      />
      <div className="sources-form__row">
        <button type="submit" className="panel-button panel-button--primary" disabled={disabled}>
          Add URL source
        </button>
      </div>
    </form>
  );
}

function EmptyIcon() {
  return (
    <svg
      aria-hidden="true"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
    </svg>
  );
}

function SourcesIcon() {
  return (
    <svg
      aria-hidden="true"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  );
}
