/**
 * General Chat — document-aware assistant frontend.
 *
 * Same UI as lci-mini but without authentication. Supports uploading
 * PDF, DOCX, and PPTX files which are parsed server-side with Docling.
 */

import { ChatPanel, ChatProvider, SessionSidebar, useChatContext } from "@openbench/chat-ui";
import { useEffect, useMemo, useRef, useState } from "react";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import { ErrorBoundary } from "./ErrorBoundary";
import { ToastProvider, useToast } from "./Toast";
import "./global.css";

const STREAM_URL = "/awp";

const SUGGESTIONS = [
  "Summarise the uploaded document",
  "What are the key points in this file?",
  "Extract all action items from this document",
  "Compare the main topics across the uploaded files",
  "What questions does this document answer?",
];

// ── Shared skeleton ──

function BadgeSkeleton({ title, rows }: { title: string; rows: number }) {
  return (
    <div className="badge-skeleton" aria-busy="true" aria-label={`${title} loading`}>
      <div className="badge-skeleton__title">{title}</div>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="badge-skeleton__row"
          style={{ width: `${60 + ((i * 13) % 30)}%` }}
        />
      ))}
    </div>
  );
}

// ── Persona badge ──

type PersonaSummary = {
  loaded: boolean;
  source?: string;
  soul_chars?: number;
  style_chars?: number;
  agents_chars?: number;
  total_chars?: number;
};

function PersonaBadge() {
  const [persona, setPersona] = useState<PersonaSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    fetch("/persona")
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((data) => { if (!cancelled) setPersona(data); })
      .catch(() => { if (!cancelled) setPersona({ loaded: false }); })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (isLoading) return <BadgeSkeleton rows={4} title="Persona" />;
  if (!persona || !persona.loaded) {
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

// ── Skill badge ──

type SkillItem = {
  name: string;
  version: string;
  description: string;
  has_tools: boolean;
  tools: string[];
  context_chars: number;
};

type SkillsResponse = {
  loaded: boolean;
  summary?: { total: number; total_tools: number; context_chars: number };
  skills: SkillItem[];
};

function SkillBadge() {
  const [data, setData] = useState<SkillsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    fetch("/skills")
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData({ loaded: false, skills: [] }); })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (isLoading) return <BadgeSkeleton rows={3} title="Skills" />;
  if (!data || !data.loaded || data.skills.length === 0) {
    return <div className="skill-badge skill-badge--empty">No skills loaded</div>;
  }

  return (
    <div className="skill-badge">
      <div className="skill-badge__title">Skills loaded ({data.skills.length})</div>
      {data.skills.map((s) => (
        <div key={s.name} className="skill-badge__item">
          <div className="skill-badge__name">
            {s.name} <span className="skill-badge__version">v{s.version}</span>
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

// ── Source Panel ──

const ACCEPTED_TYPES = ".xlsx,.xls,.pdf,.docx,.doc,.pptx,.ppt,.txt,.md,.csv,.json";

type SourceFile = {
  id: string;
  sessionId?: string;
  name: string;
  kind?: string;
  mimeType: string;
  sizeBytes: number;
  url?: string;
  type?: "file" | "audio" | "video" | "image";
  status?: "ready" | "failed";
  error?: string | null;
  extractedText?: string;
  [key: string]: unknown;
};

type UploadingEntry = { name: string; progress: number };
type SourceSearchResult = {
  sourceId: string;
  name: string;
  kind: string;
  snippet: string;
};

function fileIcon(mimeType: string): string {
  if (mimeType === "application/pdf") return "PDF";
  if (mimeType.includes("spreadsheetml") || mimeType.includes("excel")) return "XLS";
  if (mimeType.includes("wordprocessingml") || mimeType.includes("msword")) return "DOC";
  if (mimeType.includes("presentationml") || mimeType.includes("powerpoint")) return "PPT";
  if (mimeType.startsWith("text/") || mimeType === "application/json") return "TXT";
  if (mimeType === "text/html") return "URL";
  return "SRC";
}

function uploadWithProgress(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<SourceFile> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("sessionId", sessionId);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/chat/upload", true);
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) onProgress(ev.loaded / ev.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as SourceFile);
        } catch {
          reject(new Error("Invalid server response"));
        }
      } else {
        reject(new Error(`HTTP ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error"));
    xhr.send(form);
  });
}

function SourcePanel({
  sources,
  setSources,
}: {
  sources: SourceFile[];
  setSources: React.Dispatch<React.SetStateAction<SourceFile[]>>;
}) {
  const [uploading, setUploading] = useState<Map<string, UploadingEntry>>(new Map());
  const [urlValue, setUrlValue] = useState("");
  const [textValue, setTextValue] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SourceSearchResult[]>([]);
  const [isAddingUrl, setIsAddingUrl] = useState(false);
  const [isAddingText, setIsAddingText] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const { activeSessionId, createSession } = useChatContext();

  const ensureSessionId = () => activeSessionId ?? createSession();

  useEffect(() => {
    if (!activeSessionId) {
      setSources([]);
      setSearchResults([]);
      return;
    }
    let cancelled = false;
    fetch(`/chat/sources/${activeSessionId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((items: SourceFile[]) => {
        if (!cancelled) setSources(items);
      })
      .catch(() => {
        if (!cancelled) setSources([]);
      });
    return () => { cancelled = true; };
  }, [activeSessionId, setSources]);

  const handleFiles = async (files: FileList) => {
    const fileArray = Array.from(files);
    const sessionId = ensureSessionId();

    // Kick off all uploads in parallel, each with its own progress entry.
    const results = await Promise.allSettled(
      fileArray.map((file) => {
        const key = `${file.name}-${Date.now()}`;
        setUploading((prev) => new Map(prev).set(key, { name: file.name, progress: 0 }));

        return uploadWithProgress(file, sessionId, (fraction) => {
          setUploading((prev) => {
            const next = new Map(prev);
            next.set(key, { name: file.name, progress: fraction });
            return next;
          });
        }).finally(() => {
          setUploading((prev) => {
            const next = new Map(prev);
            next.delete(key);
            return next;
          });
        });
      }),
    );

    const succeeded: SourceFile[] = [];
    results.forEach((result, i) => {
      if (result.status === "fulfilled") {
        succeeded.push(result.value);
      } else {
        const msg =
          result.reason instanceof Error ? result.reason.message : String(result.reason);
        toast.show(`Failed: ${fileArray[i].name} — ${msg}`, "error");
      }
    });

    if (succeeded.length > 0) {
      setSources((prev) => [...prev, ...succeeded]);

      const names = succeeded.map((s) => s.name).join(", ");
      toast.show(`Ready: ${names}`, "success");
    }

    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) handleFiles(e.target.files);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
  };

  const addUrlSource = async () => {
    const url = urlValue.trim();
    if (!url) return;
    const sessionId = ensureSessionId();
    setIsAddingUrl(true);
    try {
      const response = await fetch(`/chat/sources/${sessionId}/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const source = (await response.json()) as SourceFile;
      setSources((prev) => [...prev, source]);
      setUrlValue("");
      toast.show(
        source.status === "failed" ? source.error || "Website source failed" : `Ready: ${source.name}`,
        source.status === "failed" ? "error" : "success",
      );
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      toast.show(`URL source failed: ${msg}`, "error");
    } finally {
      setIsAddingUrl(false);
    }
  };

  const addTextSource = async () => {
    const text = textValue.trim();
    if (!text) return;
    const sessionId = ensureSessionId();
    setIsAddingText(true);
    try {
      const response = await fetch(`/chat/sources/${sessionId}/text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Pasted text", text }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const source = (await response.json()) as SourceFile;
      setSources((prev) => [...prev, source]);
      setTextValue("");
      toast.show(
        source.status === "failed" ? source.error || "Text source failed" : "Text source ready",
        source.status === "failed" ? "error" : "success",
      );
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      toast.show(`Text source failed: ${msg}`, "error");
    } finally {
      setIsAddingText(false);
    }
  };

  const searchSources = async (query: string) => {
    setSearchQuery(query);
    const sessionId = activeSessionId;
    if (!sessionId || !query.trim()) {
      setSearchResults([]);
      return;
    }
    try {
      const params = new URLSearchParams({ q: query });
      const response = await fetch(`/chat/sources/${sessionId}/search?${params.toString()}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = (await response.json()) as { results: SourceSearchResult[] };
      setSearchResults(data.results);
    } catch {
      setSearchResults([]);
    }
  };

  const removeSource = async (id: string) => {
    const sessionId = activeSessionId;
    setSources((prev) => prev.filter((s) => s.id !== id));
    setSearchResults((prev) => prev.filter((r) => r.sourceId !== id));
    if (!sessionId) return;
    try {
      const response = await fetch(`/chat/sources/${sessionId}/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    } catch {
      toast.show("Source removed locally, but server cleanup failed", "error");
    }
  };

  const isUploading = uploading.size > 0;
  const uploadingEntries = Array.from(uploading.values());

  return (
    <div
      className="source-panel"
      onDrop={onDrop}
      onDragOver={(e) => e.preventDefault()}
    >
      <div className="source-panel__header">
        <span className="source-panel__title">Sources</span>
        <button
          type="button"
          className="source-panel__add-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading}
          title="Upload source file"
        >
          + Add
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPTED_TYPES}
          onChange={onInputChange}
          style={{ display: "none" }}
        />
      </div>

      <div className="source-panel__controls">
        <div className="source-panel__inline">
          <input
            className="source-panel__input"
            value={urlValue}
            onChange={(e) => setUrlValue(e.target.value)}
            placeholder="https://example.com"
            aria-label="Website URL"
          />
          <button
            type="button"
            className="source-panel__mini-btn"
            onClick={addUrlSource}
            disabled={isAddingUrl || !urlValue.trim()}
          >
            URL
          </button>
        </div>
        <textarea
          className="source-panel__textarea"
          value={textValue}
          onChange={(e) => setTextValue(e.target.value)}
          placeholder="Paste text source"
          aria-label="Plain text source"
          rows={3}
        />
        <button
          type="button"
          className="source-panel__wide-btn"
          onClick={addTextSource}
          disabled={isAddingText || !textValue.trim()}
        >
          Add text
        </button>
        <input
          className="source-panel__input"
          value={searchQuery}
          onChange={(e) => searchSources(e.target.value)}
          placeholder="Search sources"
          aria-label="Search sources"
        />
      </div>

      {/* In-progress uploads */}
      {uploadingEntries.map((entry) => (
        <div key={entry.name} className="source-panel__uploading">
          <span className="source-panel__uploading-name">{entry.name}</span>
          <div className="source-panel__progress-track">
            <div
              className="source-panel__progress-fill"
              style={{ width: `${Math.round(entry.progress * 100)}%` }}
            />
          </div>
          <span className="source-panel__progress-pct">
            {Math.round(entry.progress * 100)}%
          </span>
        </div>
      ))}

      {/* Completed sources */}
      {sources.length === 0 && !isUploading ? (
        <div className="source-panel__empty">
          <div className="source-panel__empty-icon">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          </div>
          <span>Drop files, add a URL, or paste text</span>
        </div>
      ) : (
        <div className="source-panel__list">
          {sources.map((s) => (
            <div
              key={s.id}
              className={`source-panel__item${s.status === "failed" ? " source-panel__item--failed" : ""}`}
            >
              <span className="source-panel__item-badge">{fileIcon(s.mimeType)}</span>
              <span className="source-panel__item-name" title={s.error ? `${s.name}: ${s.error}` : s.name}>
                {s.name}
                {s.status === "failed" && (
                  <span className="source-panel__item-error"> {s.error || "Failed"}</span>
                )}
              </span>
              <button
                type="button"
                className="source-panel__item-remove"
                onClick={() => removeSource(s.id)}
                aria-label={`Remove ${s.name}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {searchResults.length > 0 && (
        <div className="source-panel__results">
          {searchResults.map((result) => (
            <div key={`${result.sourceId}-${result.snippet}`} className="source-panel__result">
              <div className="source-panel__result-name">{result.name}</div>
              <div className="source-panel__result-snippet">{result.snippet}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Dark mode ──

function useDarkMode() {
  const [dark, setDark] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false,
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }, [dark]);

  return [dark, () => setDark((d) => !d)] as const;
}

function ThemeIcon({ dark }: { dark: boolean }) {
  if (dark) {
    return (
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
      </svg>
    );
  }
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </svg>
  );
}

// ── Layout ──

function ChatLayout() {
  const { sidebarOpen } = useChatContext();
  const [dark, toggleDark] = useDarkMode();
  const [sources, setSources] = useState<SourceFile[]>([]);
  const persistentSources = useMemo(
    () =>
      sources
        .filter((source) => source.status !== "failed")
        .map((source) => ({
          ...source,
          type: source.type ?? "file" as const,
          url: source.url ?? "",
        })),
    [sources],
  );

  return (
    <div className="chat-layout">
      {sidebarOpen && (
        <div className="lci-mini-sidebar">
          <SessionSidebar />
          <SourcePanel sources={sources} setSources={setSources} />
          <PersonaBadge />
          <SkillBadge />
        </div>
      )}
      <ChatPanel
        title="General Chat"
        suggestions={SUGGESTIONS}
        persistentAttachments={persistentSources}
        placeholder="Ask anything, or add files, websites, or text sources..."
        greeting="Hello — upload a document or ask me anything"
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
    </div>
  );
}

function Shell() {
  const toast = useToast();

  const chatConfig = useMemo(
    () => ({
      streamUrl: STREAM_URL,
      onUploadSuccess: (_localId: string, attachment: { name: string }) => {
        toast.show(`Uploaded: ${attachment.name}`, "success");
      },
      onUploadError: (file: { name: string }, error: unknown) => {
        const msg = error instanceof Error ? error.message : String(error);
        toast.show(`Upload failed for ${file.name}: ${msg}`, "error");
      },
    }),
    [toast],
  );

  return (
    <ChatProvider config={chatConfig}>
      <ErrorBoundary region="chat">
        <ChatLayout />
      </ErrorBoundary>
    </ChatProvider>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  );
}
