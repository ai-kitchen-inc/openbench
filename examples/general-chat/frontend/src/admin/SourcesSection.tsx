import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { BookIcon, XIcon } from "../brand/icons";
import { useToast } from "../Toast";
import { SOURCE_ACCEPT } from "../chat/uploads";
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
      showToast(`Gagal memuat sumber: ${readErrorMessage(error)}`, "error");
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
          showToast(`Berhasil diunggah: ${file.name}`, "success");
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
    [refresh, showToast],
  );

  return (
    <section className="panel-section" aria-label="Sumber basis pengetahuan">
      <div className="panel-section__header">
        <div>
          <div className="panel-section__title">
            <BookIcon />
            Daftar Sumber
          </div>
          <div className="panel-section__subtitle">
            Unggah dokumen, tempel teks, atau tambahkan URL sebagai sumber resmi.
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
              ? `Mengunggah ${Math.round(uploadProgress * 100)}%`
              : "Unggah Dokumen"}
          </button>
          <button
            type="button"
            className="panel-button"
            onClick={() => setAddMode(addMode === "text" ? "none" : "text")}
            disabled={isMutating}
          >
            Tempel Teks
          </button>
          <button
            type="button"
            className="panel-button"
            onClick={() => setAddMode(addMode === "url" ? "none" : "url")}
            disabled={isMutating}
          >
            Tambah URL
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
          <div className="sources-list__empty">Memuat sumber...</div>
        ) : sources.length === 0 ? (
          <div className="panel-empty">
            <span className="panel-empty__icon">
              <BookIcon size={20} />
            </span>
            <div className="panel-empty__title">Belum ada sumber</div>
            <div className="panel-empty__hint">
              Pengguna belum bisa mendapatkan jawaban sebelum Anda menambahkan minimal satu
              sumber. Unggah dokumen, tempel teks, atau tambahkan URL.
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
                      {source.error ?? "Pemrosesan sumber gagal"}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className="source-row__remove"
                  aria-label={`Hapus ${source.name}`}
                  disabled={isMutating}
                  onClick={() => void runMutation(() => deleteSource(source.id))}
                >
                  <XIcon size={14} />
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
        <button type="submit" className="panel-button panel-button--primary" disabled={disabled}>
          Tambah Sumber Teks
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
        placeholder="https://contoh.go.id/halaman-yang-diambil"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        required
      />
      <div className="sources-form__row">
        <button type="submit" className="panel-button panel-button--primary" disabled={disabled}>
          Tambah Sumber URL
        </button>
      </div>
    </form>
  );
}
