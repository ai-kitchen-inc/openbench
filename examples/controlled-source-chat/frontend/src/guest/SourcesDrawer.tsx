import { useEffect, useState } from "react";
import { apiFetch, apiPath } from "../api";
import { parseJsonResponse, readErrorMessage } from "../control-panel/sourcesApi";

type ControlledSource = {
  id: string;
  name: string;
  kind: string;
  status: string;
  url: string | null;
  textPreview?: string;
  textTruncated?: boolean;
};

/** Read-only view of the curated sources — lets users verify the source
 * names the assistant cites without being able to change anything. */
export function SourcesDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [sources, setSources] = useState<ControlledSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    void apiFetch(apiPath("/controlled/sources"))
      .then((response) => parseJsonResponse<ControlledSource[]>(response))
      .then((items) => {
        if (!cancelled) setSources(items);
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
      <aside className="drawer" role="dialog" aria-label="Knowledge base sources">
        <div className="drawer__header">
          <div className="drawer__title">Sources</div>
          <button type="button" className="drawer__close" onClick={onClose} aria-label="Close">
            <svg
              aria-hidden="true"
              width="16"
              height="16"
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
        <div className="drawer__body">
          {isLoading ? (
            <div className="guest-sources-empty">Loading sources...</div>
          ) : error ? (
            <div className="guest-sources-empty">{error}</div>
          ) : sources.length === 0 ? (
            <div className="guest-sources-empty">
              No sources are configured yet. Ask the administrator to add some.
            </div>
          ) : (
            sources.map((source) => (
              <div key={source.id} className="guest-source-item">
                <div className="guest-source-item__head">
                  <span className="source-row__badge">{source.kind.toUpperCase()}</span>
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
            ))
          )}
        </div>
      </aside>
    </>
  );
}
