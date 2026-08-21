import { useEffect, useState } from "react";
import { listAccountSources, readErrorMessage, type SharedSource } from "../account/api";
import { XIcon } from "../brand/icons";

function kindLabel(source: SharedSource): string {
  if (source.kind === "url") return "WEB";
  if (source.kind === "text") return "TEKS";
  if (source.kind === "spreadsheet") {
    return source.name.toLowerCase().endsWith(".csv") ? "CSV" : "XLSX";
  }
  if (source.kind === "image") return "GAMBAR";
  return source.kind.toUpperCase();
}

function SourceItemView({ source }: { source: SharedSource }) {
  return (
    <div className="guest-source-item">
      <div className="guest-source-item__head">
        <span className="source-row__badge">{kindLabel(source)}</span>
        <span className="guest-source-item__name">{source.name}</span>
      </div>
      {source.url && (
        <a
          className="guest-source-item__link"
          href={source.url}
          target="_blank"
          rel="noreferrer"
        >
          {source.url}
        </a>
      )}
      {source.textPreview && (
        <div className="guest-source-item__preview">
          {source.textPreview}
          {source.textTruncated ? "…" : ""}
        </div>
      )}
    </div>
  );
}

/** Read-only view of the admin-curated global + group sources — lets users
 * verify the source names the assistant cites without changing anything. */
export function SourcesDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [sources, setSources] = useState<SharedSource[]>([]);
  const [groupSources, setGroupSources] = useState<SharedSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    void listAccountSources()
      .then((items) => {
        if (cancelled) return;
        setSources(items.sources);
        setGroupSources(items.groupSources);
      })
      .catch((err) => {
        if (!cancelled) setError(readErrorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-label="Sumber basis pengetahuan">
        <div className="drawer__header">
          <div className="drawer__title">Sumber Pengetahuan</div>
          <button type="button" className="drawer__close" onClick={onClose} aria-label="Tutup">
            <XIcon size={16} />
          </button>
        </div>
        <div className="drawer__body">
          {isLoading ? (
            <div className="guest-sources-empty">Memuat sumber...</div>
          ) : error ? (
            <div className="guest-sources-empty">{error}</div>
          ) : sources.length === 0 && groupSources.length === 0 ? (
            <div className="guest-sources-empty">
              Belum ada sumber global yang dikonfigurasi. Hubungi administrator untuk
              menambahkannya.
            </div>
          ) : (
            <>
              {sources.map((source) => (
                <SourceItemView key={source.id} source={source} />
              ))}
              {groupSources.length > 0 && (
                <>
                  <div className="drawer__title">Sumber Grup</div>
                  {groupSources.map((source) => (
                    <SourceItemView key={source.id} source={source} />
                  ))}
                </>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
}
