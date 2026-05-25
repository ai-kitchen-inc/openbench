import {
  ChatPanel,
  ChatProvider,
  SessionSidebar,
  useChatContext,
  type Attachment,
} from "@openbench/chat-ui";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import { ErrorBoundary } from "./ErrorBoundary";
import { McpCatalogPanel } from "./mcp-catalog/McpCatalogPanel";
import { ToastProvider, useToast } from "./Toast";
import "./global.css";

const STREAM_URL = "/awp";
const SOURCE_ACCEPT =
  ".xlsx,.xls,.pdf,.docx,.doc,.pptx,.ppt,.txt,.md,.csv,.json,.png,.jpg,.jpeg,.webp";

const SUGGESTIONS = [
  "Help me think through this problem",
  "Draft a concise plan for my next steps",
  "Compare a few options and tradeoffs",
  "Use available tools if they help",
  "Summarize optional context I add",
];

type PersonaSummary = {
  loaded: boolean;
  soul_chars?: number;
  style_chars?: number;
  agents_chars?: number;
  total_chars?: number;
};

type SkillItem = {
  name: string;
  version: string;
};

type SkillsResponse = {
  loaded: boolean;
  summary?: { total: number; context_chars: number };
  skills: SkillItem[];
};

export type SourceItem = {
  id: string;
  sessionId: string;
  name: string;
  kind: string;
  mimeType: string;
  status: "ready" | "failed";
  error: string | null;
  sizeBytes: number;
  createdAt: string;
  url: string | null;
  extractedText?: string;
  metadata?: Record<string, unknown> | null;
};

export type DiscoveryResult = {
  id: string;
  title: string;
  url: string;
  domain: string;
  snippet: string;
  faviconUrl?: string | null;
};

type UploadingState = {
  name: string;
  progress: number;
} | null;

function BadgeSkeleton({ title, rows }: { title: string; rows: number }) {
  return (
    <div className="badge-skeleton" aria-busy="true" aria-label={`${title} loading`}>
      <div className="badge-skeleton__title">{title}</div>
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="badge-skeleton__row"
          style={{ width: `${58 + ((index * 17) % 28)}%` }}
        />
      ))}
    </div>
  );
}

function PersonaBadge() {
  const [persona, setPersona] = useState<PersonaSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    (async () => {
      try {
        const response = await fetch("/persona");
        if (cancelled) return;
        if (!response.ok) {
          setPersona({ loaded: false });
          return;
        }
        setPersona(await response.json());
      } catch {
        if (!cancelled) setPersona({ loaded: false });
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (isLoading) return <BadgeSkeleton title="Persona" rows={4} />;
  if (!persona) return null;
  if (!persona.loaded) {
    return <div className="persona-badge persona-badge--empty">No persona loaded</div>;
  }

  return (
    <div className="persona-badge">
      <div className="persona-badge__title">Persona loaded from soul/</div>
      <div className="persona-badge__row">
        <span>SOUL.md</span>
        <span>{persona.soul_chars} chars</span>
      </div>
      <div className="persona-badge__row">
        <span>STYLE.md</span>
        <span>{persona.style_chars} chars</span>
      </div>
      <div className="persona-badge__row">
        <span>AGENTS.md</span>
        <span>{persona.agents_chars} chars</span>
      </div>
      <div className="persona-badge__row persona-badge__row--total">
        <span>Total prompt</span>
        <span>{persona.total_chars} chars</span>
      </div>
    </div>
  );
}

function SkillBadge() {
  const [data, setData] = useState<SkillsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    (async () => {
      try {
        const response = await fetch("/skills");
        if (cancelled) return;
        if (!response.ok) {
          setData({ loaded: false, skills: [] });
          return;
        }
        setData(await response.json());
      } catch {
        if (!cancelled) setData({ loaded: false, skills: [] });
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (isLoading) return <BadgeSkeleton title="Skills" rows={3} />;
  if (!data) return null;
  if (!data.loaded || data.skills.length === 0) {
    return <div className="skill-badge skill-badge--empty">No skills loaded</div>;
  }

  return (
    <div className="skill-badge">
      <div className="skill-badge__title">Skills loaded ({data.skills.length})</div>
      {data.skills.map((skill) => (
        <div key={skill.name} className="skill-badge__item">
          <div className="skill-badge__name">
            {skill.name} <span className="skill-badge__version">v{skill.version}</span>
          </div>
        </div>
      ))}
      {data.summary && (
        <div className="persona-badge__row persona-badge__row--total">
          <span>Skill context</span>
          <span>{data.summary.context_chars} chars</span>
        </div>
      )}
    </div>
  );
}

function useDarkMode() {
  const [dark, setDark] = useState(() => {
    if (typeof window !== "undefined") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    return false;
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }, [dark]);

  return [dark, () => setDark((current) => !current)] as const;
}

function ThemeIcon({ dark }: { dark: boolean }) {
  if (dark) {
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
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
      </svg>
    );
  }

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
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </svg>
  );
}

function sourceToAttachment(source: SourceItem): Attachment | null {
  if (source.status !== "ready") return null;
  return {
    id: source.id,
    type: source.mimeType.startsWith("image/") ? "image" : "file",
    name: source.name,
    url: source.url ?? "",
    mimeType: source.mimeType,
    sizeBytes: source.sizeBytes,
    extractedPreview: source.extractedText,
  };
}

function sourceKindLabel(source: SourceItem): string {
  if (source.kind === "url") return "WEB";
  if (source.kind === "text") return "TEXT";
  if (source.kind === "spreadsheet") return "XLSX";
  if (source.kind === "image") return "IMAGE";
  return source.kind.toUpperCase();
}

function formatSourceMeta(source: SourceItem): string | null {
  const metadata = source.metadata ?? {};
  if (source.kind === "image") {
    const description = typeof metadata.description === "string" ? metadata.description : "";
    return description || "Image OCR ready";
  }
  if (source.url) return source.url;
  return null;
}

function readErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let payload: Record<string, unknown> = {};
  if (text) {
    try {
      payload = JSON.parse(text) as Record<string, unknown>;
    } catch {
      const compact = text.replace(/\s+/g, " ").trim();
      if (!response.ok) {
        throw new Error(
          compact || `${response.status} ${response.statusText}` || "Request failed",
        );
      }
      throw new Error("Server returned an invalid JSON response.");
    }
  }
  if (!response.ok) {
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : typeof payload?.error === "string"
          ? payload.error
          : `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }
  return payload as T;
}

function uploadSourceFile(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/chat/upload");
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total);
      }
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response as SourceItem);
        return;
      }
      const detail =
        typeof request.response?.detail === "string"
          ? request.response.detail
          : request.statusText || "Upload failed";
      reject(new Error(detail));
    });
    request.addEventListener("error", () => reject(new Error("Upload failed")));
    const form = new FormData();
    form.append("file", file);
    form.append("sessionId", sessionId);
    request.send(form);
  });
}

export function SourcePanel({
  sessionId,
  onAttachmentsChange,
}: {
  sessionId: string | null;
  onAttachmentsChange: (attachments: Attachment[]) => void;
}) {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [isLoadingSources, setIsLoadingSources] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [textInput, setTextInput] = useState("");
  const [discoveryQuery, setDiscoveryQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [discoveryResults, setDiscoveryResults] = useState<DiscoveryResult[]>([]);
  const [selectedResultIds, setSelectedResultIds] = useState<string[]>([]);
  const [discoveryError, setDiscoveryError] = useState("");
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [hasSearchedDiscovery, setHasSearchedDiscovery] = useState(false);
  const [uploading, setUploading] = useState<UploadingState>(null);

  const loadSources = useCallback(
    async (targetSessionId: string) => {
      setIsLoadingSources(true);
      try {
        const response = await fetch(`/chat/sources/${encodeURIComponent(targetSessionId)}`);
        const items = await parseJsonResponse<SourceItem[]>(response);
        setSources(items);
      } catch (error) {
        toast.show(`Could not load sources: ${readErrorMessage(error)}`, "error");
        setSources([]);
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
  }, [loadSources, onAttachmentsChange, sessionId]);

  useEffect(() => {
    onAttachmentsChange(sources.map(sourceToAttachment).filter(Boolean) as Attachment[]);
  }, [onAttachmentsChange, sources]);

  const handleUploadClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileSelection = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      if (!sessionId) return;
      const files = Array.from(event.target.files ?? []);
      if (files.length === 0) return;

      try {
        setIsMutating(true);
        for (const file of files) {
          setUploading({ name: file.name, progress: 0 });
          const record = await uploadSourceFile(file, sessionId, (fraction) => {
            setUploading({ name: file.name, progress: fraction });
          });
          const message =
            record.status === "ready"
              ? `Added source: ${record.name}`
              : `Source failed: ${record.name} - ${record.error ?? "Unknown error"}`;
          toast.show(message, record.status === "ready" ? "success" : "error");
        }
        await loadSources(sessionId);
      } catch (error) {
        toast.show(`Upload failed: ${readErrorMessage(error)}`, "error");
      } finally {
        setUploading(null);
        setIsMutating(false);
        event.target.value = "";
      }
    },
    [loadSources, sessionId, toast],
  );

  const handleAddUrl = useCallback(async () => {
    if (!sessionId) return;
    const url = urlInput.trim();
    if (!url) return;
    setIsMutating(true);
    try {
      const response = await fetch(`/chat/sources/${encodeURIComponent(sessionId)}/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const record = await parseJsonResponse<SourceItem>(response);
      setUrlInput("");
      await loadSources(sessionId);
      toast.show(
        record.status === "ready"
          ? `Added source: ${record.name}`
          : `Source failed: ${record.error ?? "Unknown error"}`,
        record.status === "ready" ? "success" : "error",
      );
    } catch (error) {
      toast.show(`Could not add website source: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  }, [loadSources, sessionId, toast, urlInput]);

  const handleAddText = useCallback(async () => {
    if (!sessionId) return;
    const text = textInput.trim();
    if (!text) return;
    setIsMutating(true);
    try {
      const response = await fetch(`/chat/sources/${encodeURIComponent(sessionId)}/text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Pasted text", text }),
      });
      const record = await parseJsonResponse<SourceItem>(response);
      setTextInput("");
      await loadSources(sessionId);
      toast.show(
        record.status === "ready"
          ? `Added source: ${record.name}`
          : `Source failed: ${record.error ?? "Unknown error"}`,
        record.status === "ready" ? "success" : "error",
      );
    } catch (error) {
      toast.show(`Could not add pasted text: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  }, [loadSources, sessionId, textInput, toast]);

  const handleDeleteSource = useCallback(
    async (sourceId: string) => {
      if (!sessionId) return;
      setIsMutating(true);
      try {
        const response = await fetch(
          `/chat/sources/${encodeURIComponent(sessionId)}/${encodeURIComponent(sourceId)}`,
          { method: "DELETE" },
        );
        await parseJsonResponse<{ ok: boolean }>(response);
        await loadSources(sessionId);
      } catch (error) {
        toast.show(`Could not remove source: ${readErrorMessage(error)}`, "error");
      } finally {
        setIsMutating(false);
      }
    },
    [loadSources, sessionId, toast],
  );

  const handleDiscoverySubmit = useCallback(
    async (event?: FormEvent<HTMLFormElement>) => {
      event?.preventDefault();
      const query = discoveryQuery.trim();
      if (!query) return;
      if (query === submittedQuery && hasSearchedDiscovery && !discoveryError) return;

      setDiscoveryLoading(true);
      setDiscoveryError("");
      setHasSearchedDiscovery(true);
      setSelectedResultIds([]);

      try {
        const response = await fetch(`/chat/sources/discover?q=${encodeURIComponent(query)}`);
        const payload = await parseJsonResponse<{ query: string; results: DiscoveryResult[] }>(response);
        setSubmittedQuery(payload.query);
        setDiscoveryResults(payload.results);
      } catch (error) {
        setDiscoveryError(readErrorMessage(error));
      } finally {
        setDiscoveryLoading(false);
      }
    },
    [discoveryError, discoveryQuery, hasSearchedDiscovery, submittedQuery],
  );

  const toggleDiscoverySelection = useCallback((resultId: string) => {
    setSelectedResultIds((current) =>
      current.includes(resultId)
        ? current.filter((item) => item !== resultId)
        : [...current, resultId],
    );
  }, []);

  const handleAddSelectedSources = useCallback(async () => {
    if (!sessionId || selectedResultIds.length === 0) return;
    const selected = discoveryResults.filter((result) => selectedResultIds.includes(result.id));
    if (selected.length === 0) return;

    setIsMutating(true);
    try {
      const records = await Promise.all(
        selected.map(async (result) => {
          const response = await fetch(`/chat/sources/${encodeURIComponent(sessionId)}/url`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: result.url }),
          });
          return parseJsonResponse<SourceItem>(response);
        }),
      );

      const readyCount = records.filter((record) => record.status === "ready").length;
      const failedCount = records.length - readyCount;
      await loadSources(sessionId);
      setSelectedResultIds([]);
      toast.show(
        failedCount === 0
          ? `Added ${readyCount} web source${readyCount === 1 ? "" : "s"}`
          : `Added ${readyCount}, failed ${failedCount}`,
        failedCount === 0 ? "success" : "error",
      );
    } catch (error) {
      toast.show(`Could not add selected links: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  }, [discoveryResults, loadSources, selectedResultIds, sessionId, toast]);

  return (
    <div className="source-panel">
      <div className="source-panel__header">
        <div className="source-panel__title">Sources</div>
        <button
          type="button"
          className="source-panel__add-btn"
          onClick={handleUploadClick}
          disabled={!sessionId || isMutating}
        >
          Upload
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={SOURCE_ACCEPT}
          onChange={handleFileSelection}
          hidden
        />
      </div>

      <div className="source-panel__controls">
        <div className="source-panel__inline">
          <input
            className="source-panel__input"
            type="url"
            placeholder="Add website URL"
            value={urlInput}
            onChange={(event) => setUrlInput(event.target.value)}
          />
          <button
            type="button"
            className="source-panel__mini-btn"
            onClick={() => void handleAddUrl()}
            disabled={!sessionId || isMutating || !urlInput.trim()}
          >
            Add
          </button>
        </div>

        <textarea
          className="source-panel__textarea"
          placeholder="Paste text source"
          value={textInput}
          onChange={(event) => setTextInput(event.target.value)}
        />
        <button
          type="button"
          className="source-panel__wide-btn"
          onClick={() => void handleAddText()}
          disabled={!sessionId || isMutating || !textInput.trim()}
        >
          Add text source
        </button>
      </div>

      <form className="source-panel__discovery" onSubmit={(event) => void handleDiscoverySubmit(event)}>
        <div className="source-panel__title source-panel__title--section">Discover sources</div>
        <div className="source-panel__inline">
          <input
            className="source-panel__input"
            type="search"
            placeholder="Search the web for sources"
            value={discoveryQuery}
            onChange={(event) => setDiscoveryQuery(event.target.value)}
          />
          <button
            type="submit"
            className="source-panel__mini-btn"
            disabled={discoveryLoading || !discoveryQuery.trim()}
          >
            Search
          </button>
        </div>

        {discoveryLoading && <div className="source-panel__state">Searching the web...</div>}
        {!discoveryLoading && discoveryError && (
          <div className="source-panel__state source-panel__state--error">{discoveryError}</div>
        )}
        {!discoveryLoading &&
          !discoveryError &&
          hasSearchedDiscovery &&
          submittedQuery &&
          discoveryResults.length === 0 && (
            <div className="source-panel__state">No results for "{submittedQuery}".</div>
          )}

        {discoveryResults.length > 0 && (
          <>
            <div className="source-panel__results source-panel__results--discovery">
              {discoveryResults.map((result) => {
                const isSelected = selectedResultIds.includes(result.id);
                return (
                  <label
                    key={result.id}
                    className={`source-panel__discovery-result${isSelected ? " source-panel__discovery-result--selected" : ""}`}
                  >
                    <input
                      type="checkbox"
                      className="source-panel__checkbox"
                      checked={isSelected}
                      onChange={() => toggleDiscoverySelection(result.id)}
                    />
                    <div className="source-panel__discovery-body">
                      <div className="source-panel__discovery-meta">
                        {result.faviconUrl ? (
                          <img
                            className="source-panel__favicon"
                            src={result.faviconUrl}
                            alt=""
                            aria-hidden="true"
                          />
                        ) : (
                          <span className="source-panel__favicon source-panel__favicon--placeholder" />
                        )}
                        <span className="source-panel__discovery-domain">{result.domain}</span>
                      </div>
                      <a
                        href={result.url}
                        target="_blank"
                        rel="noreferrer"
                        className="source-panel__discovery-link"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {result.title}
                      </a>
                      <div className="source-panel__discovery-url">{result.url}</div>
                      <div className="source-panel__result-snippet">{result.snippet}</div>
                    </div>
                  </label>
                );
              })}
            </div>
            <button
              type="button"
              className="source-panel__wide-btn"
              onClick={() => void handleAddSelectedSources()}
              disabled={!sessionId || isMutating || selectedResultIds.length === 0}
            >
              Add selected sources
            </button>
          </>
        )}
      </form>

      {uploading && (
        <div className="source-panel__uploading">
          <span className="source-panel__uploading-name">{uploading.name}</span>
          <div className="source-panel__progress-track" aria-hidden="true">
            <div
              className="source-panel__progress-fill"
              style={{ width: `${Math.round(uploading.progress * 100)}%` }}
            />
          </div>
          <span className="source-panel__progress-pct">
            {Math.round(uploading.progress * 100)}%
          </span>
        </div>
      )}

      <div className="source-panel__title source-panel__title--section">Added sources</div>
      {isLoadingSources ? (
        <div className="source-panel__state">Loading sources...</div>
      ) : sources.length === 0 ? (
        <div className="source-panel__empty">
          <div className="source-panel__empty-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M14 2H6a2 2 0 0 0-2 2v16l4-3 4 3 4-3 4 3V8z" />
              <path d="M14 2v6h6" />
            </svg>
          </div>
          <div>Add files, websites, images, or text as optional context.</div>
        </div>
      ) : (
        <div className="source-panel__list">
          {sources.map((source) => {
            const meta = formatSourceMeta(source);
            return (
              <div
                key={source.id}
                className={`source-panel__item${source.status === "failed" ? " source-panel__item--failed" : ""}`}
              >
                <div className="source-panel__item-badge">{sourceKindLabel(source)}</div>
                <div className="source-panel__item-main">
                  <div className="source-panel__item-name">{source.name}</div>
                  {meta && <div className="source-panel__item-meta">{meta}</div>}
                  {source.status === "failed" && (
                    <div className="source-panel__item-error">{source.error ?? "Source processing failed"}</div>
                  )}
                </div>
                <button
                  type="button"
                  className="source-panel__item-remove"
                  aria-label={`Remove ${source.name}`}
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

function ChatLayout({ persistentAttachments, setPersistentAttachments }: {
  persistentAttachments: Attachment[];
  setPersistentAttachments: (attachments: Attachment[]) => void;
}) {
  const { activeSessionId, sidebarOpen } = useChatContext();
  const [dark, toggleDark] = useDarkMode();
  const [mcpCatalogOpen, setMcpCatalogOpen] = useState(false);

  return (
    <div className="chat-layout">
      {sidebarOpen && (
        <div className="lci-mini-sidebar">
          <SessionSidebar />
          <button
            type="button"
            className="mcp-servers-button"
            onClick={() => setMcpCatalogOpen(true)}
            aria-label="Open MCP Servers"
          >
            <span className="mcp-servers-button__icon" aria-hidden="true">
              MCP
            </span>
            <span>
              <strong>MCP servers</strong>
              <span>Manage tools</span>
            </span>
          </button>
          <SourcePanel
            sessionId={activeSessionId}
            onAttachmentsChange={setPersistentAttachments}
          />
          <PersonaBadge />
          <SkillBadge />
        </div>
      )}
      <ChatPanel
        title="General Chat"
        suggestions={SUGGESTIONS}
        placeholder="Ask anything, add sources, or discover useful links..."
        greeting="Welcome to General Chat"
        persistentAttachments={persistentAttachments}
        headerRight={
          <button
            type="button"
            className="theme-toggle"
            onClick={toggleDark}
            title={dark ? "Switch to light mode" : "Switch to dark mode"}
            aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
          >
            <ThemeIcon dark={dark} />
          </button>
        }
      />
      <McpCatalogPanel open={mcpCatalogOpen} onClose={() => setMcpCatalogOpen(false)} />
    </div>
  );
}

function ChatShell() {
  const toast = useToast();
  const [persistentAttachments, setPersistentAttachments] = useState<Attachment[]>([]);

  const chatConfig = useMemo(
    () => ({
      streamUrl: STREAM_URL,
      onUploadSuccess: (_localId: string, attachment: { name: string }) => {
        toast.show(`Uploaded: ${attachment.name}`, "success");
      },
      onUploadError: (file: { name: string }, error: unknown) => {
        toast.show(`Upload failed for ${file.name}: ${readErrorMessage(error)}`, "error");
      },
    }),
    [toast],
  );

  return (
    <ChatProvider config={chatConfig}>
      <ErrorBoundary region="chat">
        <ChatLayout
          persistentAttachments={persistentAttachments}
          setPersistentAttachments={setPersistentAttachments}
        />
      </ErrorBoundary>
    </ChatProvider>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <ChatShell />
    </ToastProvider>
  );
}
