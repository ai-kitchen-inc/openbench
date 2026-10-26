import { useCallback, useEffect, useState } from "react";
import {
  exportAuditCsv,
  getAuditEntries,
  readErrorMessage,
  type AuditEntry,
  type AuditFilters,
} from "../../account/api";
import { useToast } from "../../Toast";
import { COMMON } from "../../i18n/id";

const PAGE_SIZE = 50;

function formatTimestamp(ts: string): string {
  const parsed = new Date(ts);
  if (Number.isNaN(parsed.getTime())) return ts;
  return parsed.toLocaleString("id-ID");
}

function detailSummary(entry: AuditEntry): string {
  const keys = Object.keys(entry.detail ?? {});
  if (!keys.length) return "";
  return keys.map((key) => `${key}: ${String(entry.detail[key])}`).join(" · ");
}

export function AuditPage() {
  const { show: showToast } = useToast();
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [isExporting, setIsExporting] = useState(false);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [applied, setApplied] = useState<AuditFilters>({});

  const load = useCallback(
    async (filters: AuditFilters, offset: number) => {
      setIsLoading(true);
      setLoadError("");
      try {
        const result = await getAuditEntries(filters, PAGE_SIZE, offset);
        setItems((previous) => (offset === 0 ? result.items : [...previous, ...result.items]));
        setTotal(result.total);
      } catch (error) {
        setLoadError(readErrorMessage(error));
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load({}, 0);
  }, [load]);

  const applyFilters = useCallback(() => {
    const filters: AuditFilters = {
      actor: actor.trim() || undefined,
      action: action.trim() || undefined,
      // Date inputs give YYYY-MM-DD; pad "until" to the end of that day so
      // the lexicographic ISO comparison includes it.
      since: since ? `${since}T00:00:00` : undefined,
      until: until ? `${until}T23:59:59` : undefined,
    };
    setApplied(filters);
    void load(filters, 0);
  }, [action, actor, load, since, until]);

  const handleExport = useCallback(async () => {
    setIsExporting(true);
    try {
      const blob = await exportAuditCsv(applied);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `audit-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      showToast("Ekspor CSV dimulai.", "success");
    } catch (error) {
      showToast(`Gagal mengekspor audit: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsExporting(false);
    }
  }, [applied, showToast]);

  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Jejak audit siapa-melakukan-apa: login gagal, perubahan admin, unggahan sumber,
          penghapusan sesi, dan percakapan.
        </div>
      </div>

      <section className="panel-section" aria-label="Jejak audit">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Jejak Audit</div>
            <div className="panel-section__subtitle">{total} entri tercatat.</div>
          </div>
          <button
            type="button"
            className="panel-button"
            disabled={isExporting}
            onClick={() => void handleExport()}
          >
            {isExporting ? "Mengekspor..." : "Ekspor CSV"}
          </button>
        </div>
        <div className="panel-section__body">
          <form
            className="sources-form"
            onSubmit={(event) => {
              event.preventDefault();
              applyFilters();
            }}
          >
            <div className="sources-form__row">
              <input
                type="text"
                placeholder="Pelaku (email)"
                aria-label="Pelaku"
                value={actor}
                onChange={(event) => setActor(event.target.value)}
              />
              <input
                type="text"
                placeholder="Aksi (mis. user.add)"
                aria-label="Aksi"
                value={action}
                onChange={(event) => setAction(event.target.value)}
              />
              <input
                type="date"
                aria-label="Sejak"
                value={since}
                onChange={(event) => setSince(event.target.value)}
              />
              <input
                type="date"
                aria-label="Sampai"
                value={until}
                onChange={(event) => setUntil(event.target.value)}
              />
              <button type="submit" className="panel-button panel-button--primary">
                Terapkan
              </button>
            </div>
          </form>

          {isLoading && items.length === 0 ? (
            <div className="sources-list__empty">{COMMON.loading}</div>
          ) : loadError ? (
            <div className="sources-list__empty">
              Gagal memuat audit: {loadError}{" "}
              <button
                type="button"
                className="panel-button"
                onClick={() => void load(applied, 0)}
              >
                {COMMON.retry}
              </button>
            </div>
          ) : items.length === 0 ? (
            <div className="sources-list__empty">Tidak ada entri audit.</div>
          ) : (
            <div className="sources-list">
              {items.map((entry, index) => (
                <div className="source-row" key={`${entry.ts}-${index}`}>
                  <span
                    className={`source-row__badge${entry.status === "ok" ? " source-row__badge--filled" : ""}`}
                  >
                    {entry.status}
                  </span>
                  <div className="source-row__main">
                    <div className="source-row__name">
                      {entry.action}
                      {entry.target ? ` — ${entry.target}` : ""}
                    </div>
                    <div className="source-row__meta">
                      {formatTimestamp(entry.ts)}
                      {entry.actor ? ` · ${entry.actor}` : ""}
                      {entry.role ? ` (${entry.role})` : ""}
                      {detailSummary(entry) ? ` · ${detailSummary(entry)}` : ""}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {items.length < total && !isLoading && (
            <button
              type="button"
              className="panel-button"
              onClick={() => void load(applied, items.length)}
            >
              Muat lebih banyak
            </button>
          )}
        </div>
      </section>
    </>
  );
}
