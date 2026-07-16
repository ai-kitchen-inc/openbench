import {
  ChatPanel,
  ChatProvider,
  SessionSidebar,
  SurfaceRenderer,
  useChatContext,
  type A2UIComponent,
  type A2UISurface,
  type Attachment,
  type AttachmentUploadOptions,
  type ChatConfig,
  type ChatMessage,
  type SurfaceFooterRenderer,
} from "@openbench/chat-ui";
import { onAuthStateChanged, signInWithPopup, signOut, type User } from "firebase/auth";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import { apiFetch, apiPath, authHeaders, setAuthTokenProvider, transcribeAudio } from "./api";
import { ErrorBoundary } from "./ErrorBoundary";
import { getFirebaseAuth, googleProvider, isFirebaseConfigured } from "./firebase";
import { FunctionsPanel } from "./functions/FunctionsPanel";
import { McpCatalogPanel } from "./mcp-catalog/McpCatalogPanel";
import { ToastProvider, useToast } from "./Toast";
import "./global.css";

const STREAM_URL = apiPath("/awp");
export const SOURCE_ACCEPT =
  ".xlsx,.xls,.pdf,.epub,.docx,.doc,.pptx,.ppt,.txt,.md,.markdown,.html,.htm,.csv,.json," +
  ".png,.jpg,.jpeg,.webp,.gif,.heic,.heif,.tiff,.tif,.bmp,.svg," +
  ".mp3,.wav,.m4a,.ogg,.aac,.flac," +
  ".mp4,.webm,.mov,.avi";
export const DIRECT_UPLOAD_THRESHOLD_BYTES = 25 * 1024 * 1024;
const DIRECT_UPLOAD_POLL_INTERVAL_MS = 2000;
const DIRECT_UPLOAD_MAX_POLLS = 90;

const SUGGESTIONS = [
  "Help me think through this problem",
  "Draft a concise plan for my next steps",
  "Compare a few options and tradeoffs",
  "Use available tools if they help",
  "Summarize optional context I add",
  "Create a dashboard from my spreadsheet",
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
  status: "ready" | "failed" | "processing";
  error: string | null;
  sizeBytes: number;
  createdAt: string;
  url: string | null;
  extractedText?: string;
  metadata?: Record<string, unknown> | null;
};


type DirectUploadInitiateResponse = {
  fileId: string;
  uploadUrl: string;
  method?: string;
  headers?: Record<string, string>;
  source: SourceItem;
};

type DirectUploadStatusResponse = {
  status?: string;
  fileId?: string;
  source: SourceItem;
};

function normalizeDirectUploadStatus(payload: DirectUploadStatusResponse | SourceItem): DirectUploadStatusResponse {
  if ("source" in payload && payload.source) return payload;
  const source = payload as SourceItem;
  const fileId =
    typeof source.metadata?.fileId === "string" ? source.metadata.fileId : undefined;
  return {
    status: source.status,
    fileId,
    source,
  };
}

type DashboardArtifact = {
  key: string;
  messageId: string;
  surfaceId: string;
  componentId: string;
  title: string;
  url?: string;
  fileName: string;
  summary: string;
  fileSize?: number;
  surface: A2UISurface;
};

function componentString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function componentNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function componentValue(component: A2UIComponent, key: string): unknown {
  if (component[key] !== undefined) return component[key];
  const nestedProperties = component.properties;
  if (isRecord(nestedProperties)) return nestedProperties[key];
  return undefined;
}

function hasDashboardData(component: A2UIComponent): boolean {
  return Boolean(
    componentValue(component, "viewModel") ??
      componentValue(component, "view_model") ??
      componentValue(component, "datasets") ??
      componentValue(component, "kpis") ??
      componentValue(component, "sections"),
  );
}

function dashboardArtifactSurface(
  messageId: string,
  sourceSurface: A2UISurface,
  component: A2UIComponent,
): A2UISurface {
  const rootComponent = { ...component, id: "root" };
  return {
    surfaceId: `${messageId}-${sourceSurface.surfaceId}-${component.id}-dashboard-artifact`,
    catalogId: sourceSurface.catalogId,
    components: new Map([["root", rootComponent]]),
    dataModel: sourceSurface.dataModel ?? {},
    theme: sourceSurface.theme,
    sendDataModel: sourceSurface.sendDataModel,
  };
}

export function findLatestDashboard(messages: ChatMessage[]): DashboardArtifact | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    const surfaces = message.surfaces ?? [];
    for (let surfaceIndex = surfaces.length - 1; surfaceIndex >= 0; surfaceIndex -= 1) {
      const surface = surfaces[surfaceIndex];
      // Persisted legacy sessions can carry surface stubs without a
      // components Map — skip them instead of crashing the chat layout.
      const surfaceComponents = surface?.components;
      if (!surfaceComponents || typeof surfaceComponents.values !== "function") continue;
      const components = Array.from(surfaceComponents.values()).reverse();
      for (const component of components) {
        if (component.component !== "ObDashboardFrame") continue;
        const url = componentString(
          componentValue(component, "dashboardUrl") ?? componentValue(component, "url"),
        );
        if (!url && !hasDashboardData(component)) continue;
        return {
          key: `${message.id}:${surface.surfaceId}:${component.id}`,
          messageId: message.id,
          surfaceId: surface.surfaceId,
          componentId: component.id,
          title: componentString(componentValue(component, "title")) || "Dashboard",
          url: url || undefined,
          fileName: componentString(componentValue(component, "fileName")) || "dashboard.html",
          summary: componentString(
            componentValue(component, "summary") ?? componentValue(component, "description"),
          ),
          fileSize: componentNumber(componentValue(component, "fileSize")),
          surface: dashboardArtifactSurface(message.id, surface, component),
        };
      }
    }
  }
  return null;
}

function dashboardArtifactsForSurface(
  message: ChatMessage,
  surface: A2UISurface,
): DashboardArtifact[] {
  const surfaceComponents = surface?.components;
  if (!surfaceComponents || typeof surfaceComponents.values !== "function") return [];
  const artifacts: DashboardArtifact[] = [];
  for (const component of surfaceComponents.values()) {
    if (component.component !== "ObDashboardFrame") continue;
    const url = componentString(
      componentValue(component, "dashboardUrl") ?? componentValue(component, "url"),
    );
    if (!url && !hasDashboardData(component)) continue;
    artifacts.push({
      key: `${message.id}:${surface.surfaceId}:${component.id}`,
      messageId: message.id,
      surfaceId: surface.surfaceId,
      componentId: component.id,
      title: componentString(componentValue(component, "title")) || "Dashboard",
      url: url || undefined,
      fileName: componentString(componentValue(component, "fileName")) || "dashboard.html",
      summary: componentString(
        componentValue(component, "summary") ?? componentValue(component, "description"),
      ),
      fileSize: componentNumber(componentValue(component, "fileSize")),
      surface: dashboardArtifactSurface(message.id, surface, component),
    });
  }
  return artifacts;
}

export function findDashboardArtifacts(messages: ChatMessage[]): DashboardArtifact[] {
  const artifacts: DashboardArtifact[] = [];
  for (const message of messages) {
    const surfaces = message.surfaces ?? [];
    for (const surface of surfaces) {
      artifacts.push(...dashboardArtifactsForSurface(message, surface));
    }
  }
  return artifacts;
}

function formatArtifactSize(value: number | undefined): string {
  if (value == null) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function DashboardArtifactPanel({
  artifact,
  isMaximized = false,
  onToggleMaximized,
  onClose,
}: {
  artifact: DashboardArtifact;
  isMaximized?: boolean;
  onToggleMaximized?: () => void;
  onClose: () => void;
}) {
  const sizeText = formatArtifactSize(artifact.fileSize);
  return (
    <aside
      className={`dashboard-artifact${isMaximized ? " dashboard-artifact--maximized" : ""}`}
      aria-label="Dashboard artifact"
    >
      <div className="dashboard-artifact__header">
        <div className="dashboard-artifact__title-wrap">
          <div className="dashboard-artifact__eyebrow">Dashboard</div>
          <h2 className="dashboard-artifact__title">{artifact.title}</h2>
          <div className="dashboard-artifact__meta">
            {artifact.fileName}
            {sizeText ? ` - ${sizeText}` : ""}
          </div>
        </div>
        {artifact.url && (
          <a
            className="dashboard-artifact__icon-btn"
            href={artifact.url}
            target="_blank"
            rel="noreferrer"
            aria-label="Open dashboard export in a new tab"
            title="Open dashboard export"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M15 3h6v6" />
              <path d="M10 14 21 3" />
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            </svg>
          </a>
        )}
        <button
          type="button"
          className="dashboard-artifact__icon-btn"
          onClick={onToggleMaximized}
          aria-label={isMaximized ? "Minimize dashboard panel" : "Maximize dashboard panel"}
          title={isMaximized ? "Minimize dashboard" : "Maximize dashboard"}
        >
          {isMaximized ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M8 3v5H3" />
              <path d="M21 8h-5V3" />
              <path d="M16 21v-5h5" />
              <path d="M3 16h5v5" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M15 3h6v6" />
              <path d="M9 21H3v-6" />
              <path d="M21 3 14 10" />
              <path d="M3 21l7-7" />
            </svg>
          )}
        </button>
        <button
          type="button"
          className="dashboard-artifact__icon-btn"
          onClick={onClose}
          aria-label="Close dashboard panel"
          title="Close dashboard"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>
      </div>
      {artifact.summary && <div className="dashboard-artifact__summary">{artifact.summary}</div>}
      <div className="dashboard-artifact__surface">
        <SurfaceRenderer surface={artifact.surface} />
      </div>
    </aside>
  );
}

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
        const response = await apiFetch(apiPath("/persona"));
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
        const response = await apiFetch(apiPath("/skills"));
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
  const metadata = source.metadata ?? {};
  const imagePath =
    typeof metadata.samSegmentationPath === "string"
      ? metadata.samSegmentationPath
      : typeof metadata.imageSearchPath === "string"
        ? metadata.imageSearchPath
        : undefined;
  return {
    id: source.id,
    type: source.mimeType.startsWith("image/") ? "image" : "file",
    name: source.name,
    url: source.url ?? "",
    mimeType: source.mimeType,
    sizeBytes: source.sizeBytes,
    path: imagePath,
    extractedText: source.extractedText,
    extractedPreview: source.extractedText,
  };
}

function fileIdForSource(source: SourceItem): string | undefined {
  const fileId = source.metadata?.fileId;
  return typeof fileId === "string" && fileId ? fileId : undefined;
}

function sourceToComposerAttachment(source: SourceItem): Attachment {
  const readyAttachment = sourceToAttachment(source);
  if (readyAttachment) return readyAttachment;

  const metadata = source.metadata ?? {};
  const imagePath =
    typeof metadata.samSegmentationPath === "string"
      ? metadata.samSegmentationPath
      : typeof metadata.imageSearchPath === "string"
        ? metadata.imageSearchPath
        : undefined;
  const errorText =
    source.extractedText ||
    source.error ||
    `Source processing ${source.status === "failed" ? "failed" : "did not finish"} for ${source.name}.`;

  return {
    id: source.id,
    type: source.mimeType.startsWith("image/") ? "image" : "file",
    name: source.name,
    url: source.url ?? "",
    mimeType: source.mimeType,
    sizeBytes: source.sizeBytes,
    path: imagePath,
    extractedText: errorText,
    extractedPreview: errorText,
  };
}

function sourceKindLabel(source: SourceItem): string {
  if (source.kind === "url") return "WEB";
  if (source.kind === "text") return "TEXT";
  if (source.kind === "spreadsheet") {
    return source.name.toLowerCase().endsWith(".csv") ? "CSV" : "XLSX";
  }
  if (source.kind === "image") return "IMAGE";
  return source.kind.toUpperCase();
}

function formatSourceMeta(source: SourceItem): string | null {
  const metadata = source.metadata ?? {};
  if (source.status === "processing") {
    const parseStatus = typeof metadata.parseStatus === "string" ? metadata.parseStatus : "";
    return parseStatus ? `Processing: ${parseStatus}` : "Processing source";
  }
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

function xhrUpload(
  method: string,
  url: string,
  body: XMLHttpRequestBodyInit,
  headers: Record<string, string> | undefined,
  onProgress: (fraction: number) => void,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(method, url);
    request.responseType = "json";
    for (const [key, value] of Object.entries(headers ?? {})) {
      if (key.toLowerCase() === "content-length") continue;
      request.setRequestHeader(key, value);
    }
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total);
      }
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response);
        return;
      }
      const detail =
        typeof request.response?.detail === "string"
          ? request.response.detail
          : request.statusText || "Upload failed";
      reject(new Error(detail));
    });
    request.addEventListener("error", () => {
      reject(new Error("Network error while uploading. Check API HTTPS and bucket CORS settings."));
    });
    request.send(body);
  });
}

async function uploadMultipartSourceFile(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  const form = new FormData();
  form.append("file", file);
  form.append("sessionId", sessionId);
  return (await xhrUpload("POST", apiPath("/chat/upload"), form, await authHeaders(), onProgress)) as SourceItem;
}

async function uploadLargeSourceFile(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  const initiateResponse = await apiFetch(apiPath("/chat/uploads/initiate"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      mimeType: file.type || "application/octet-stream",
      sizeBytes: file.size,
      sessionId,
    }),
  });
  const session = await parseJsonResponse<DirectUploadInitiateResponse>(initiateResponse);
  await xhrUpload(session.method ?? "PUT", session.uploadUrl, file, session.headers, (fraction) => {
    onProgress(Math.min(fraction * 0.95, 0.95));
  });
  onProgress(0.98);
  const completeResponse = await apiFetch(apiPath("/chat/uploads/complete"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fileId: session.fileId, sessionId }),
  });
  const completed = await parseJsonResponse<DirectUploadStatusResponse>(completeResponse);
  onProgress(1);
  return completed.source;
}

function uploadSourceFile(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<SourceItem> {
  if (file.size > DIRECT_UPLOAD_THRESHOLD_BYTES) {
    return uploadLargeSourceFile(file, sessionId, onProgress);
  }
  return uploadMultipartSourceFile(file, sessionId, onProgress);
}

async function fetchUploadStatus(
  fileId: string,
  sessionId: string,
  options: { includeText?: boolean } = {},
): Promise<DirectUploadStatusResponse> {
  const params = new URLSearchParams({ sessionId });
  const includeText = options.includeText ?? false;
  if (includeText) params.set("includeText", "true");
  const response = await apiFetch(
    apiPath(`/chat/uploads/${encodeURIComponent(fileId)}?${params.toString()}`),
  );
  return normalizeDirectUploadStatus(
    await parseJsonResponse<DirectUploadStatusResponse | SourceItem>(response),
  );
}

async function pollUploadedSource(
  fileId: string,
  sessionId: string,
  options: { includeText?: boolean } = {},
): Promise<SourceItem> {
  const includeText = options.includeText ?? false;
  for (let attempt = 0; attempt < DIRECT_UPLOAD_MAX_POLLS; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, DIRECT_UPLOAD_POLL_INTERVAL_MS));
    const status = await fetchUploadStatus(fileId, sessionId, { includeText });
    if (status.source.status === "ready" || status.source.status === "failed") {
      return status.source;
    }
  }
  throw new Error("Upload is still processing. Try again in a moment.");
}

export async function uploadComposerAttachment(
  file: File,
  sessionId: string,
  onProgress: (fraction: number) => void,
): Promise<Attachment> {
  const uploadedSource = await uploadSourceFile(file, sessionId, onProgress);
  const fileId = fileIdForSource(uploadedSource);
  let finalSource = uploadedSource;

  if (fileId) {
    if (uploadedSource.status === "processing") {
      finalSource = await pollUploadedSource(fileId, sessionId, { includeText: true });
    } else {
      finalSource = (await fetchUploadStatus(fileId, sessionId, { includeText: true })).source;
    }
  }

  if (finalSource.status === "processing") {
    throw new Error("Upload is still processing. Try again in a moment.");
  }
  return sourceToComposerAttachment(finalSource);
}

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

  const loadSources = useCallback(
    async (targetSessionId: string): Promise<SourceItem[]> => {
      setIsLoadingSources(true);
      try {
        const response = await apiFetch(apiPath(`/chat/sources/${encodeURIComponent(targetSessionId)}`));
        const items = await parseJsonResponse<SourceItem[]>(response);
        setSources(items);
        return items;
      } catch (error) {
        toast.show(`Could not load sources: ${readErrorMessage(error)}`, "error");
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
  }, [refreshToken, sessionId]);

  useEffect(() => {
    onAttachmentsChange(sources.map(sourceToAttachment).filter(Boolean) as Attachment[]);
  }, [onAttachmentsChange, sources]);

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
        toast.show(`Could not remove source: ${readErrorMessage(error)}`, "error");
      } finally {
        setIsMutating(false);
      }
    },
    [loadSources, sessionId, toast],
  );

  return (
    <div className="source-panel">
      <div className="source-panel__header">
        <div className="source-panel__title">Sources</div>
      </div>

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
                className={`source-panel__item${source.status === "failed" ? " source-panel__item--failed" : ""}${source.status === "processing" ? " source-panel__item--processing" : ""}`}
              >
                <div className="source-panel__item-badge">{sourceKindLabel(source)}</div>
                <div className="source-panel__item-main">
                  <div className="source-panel__item-name">{source.name}</div>
                  {meta && <div className="source-panel__item-meta">{meta}</div>}
                  {source.status === "failed" && (
                    <div className="source-panel__item-error">{source.error ?? "Source processing failed"}</div>
                  )}
                  {source.status === "processing" && (
                    <div className="source-panel__item-meta">Queued for parsing</div>
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

type SettingsView = "artifact" | "tools" | "persona";
type ToolsView = "mcp" | "function";

function SidebarSettingsButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="sidebar-settings-button"
      onClick={onClick}
      aria-label="Open Settings"
    >
      <span className="sidebar-settings-button__icon" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1A2 2 0 1 1 4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.3 7A2 2 0 1 1 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3h.1A1.7 1.7 0 0 0 10 3V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1A2 2 0 1 1 19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1A1.7 1.7 0 0 0 21 10h.1a2 2 0 1 1 0 4H21a1.7 1.7 0 0 0-1.6 1Z" />
        </svg>
      </span>
      <span>Settings</span>
    </button>
  );
}

function SettingsDialog({
  open,
  onClose,
  sessionId,
  sourceRefreshToken,
  onAttachmentsChange,
}: {
  open: boolean;
  onClose: () => void;
  sessionId: string | null;
  sourceRefreshToken: number;
  onAttachmentsChange: (attachments: Attachment[]) => void;
}) {
  const [view, setView] = useState<SettingsView>("artifact");
  const [toolsView, setToolsView] = useState<ToolsView>("mcp");

  useEffect(() => {
    if (open) {
      setView("artifact");
      setToolsView("mcp");
    }
  }, [open]);

  if (!open) return null;

  return (
    <div className="settings-dialog" role="presentation">
      <div
        className="settings-dialog__panel"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
      >
        <div className="settings-dialog__header">
          <div>
            <h2>Settings</h2>
            <p>Manage artifacts, tools, and persona.</p>
          </div>
          <button type="button" className="settings-dialog__close" onClick={onClose} aria-label="Back to chat">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M19 12H5" />
              <path d="m12 19-7-7 7-7" />
            </svg>
            <span>Back to chat</span>
          </button>
        </div>
        <div className="settings-dialog__body">
          <nav className="settings-dialog__nav" aria-label="Settings sections">
            <button type="button" className={view === "artifact" ? "is-active" : ""} onClick={() => setView("artifact")}>
              Artifact
            </button>
            <button type="button" className={view === "tools" ? "is-active" : ""} onClick={() => setView("tools")}>
              Tools
            </button>
            <button type="button" className={view === "persona" ? "is-active" : ""} onClick={() => setView("persona")}>
              Persona
            </button>
          </nav>
          <section className="settings-dialog__content">
            {view === "artifact" && (
              <SourcePanel
                sessionId={sessionId}
                onAttachmentsChange={onAttachmentsChange}
                refreshToken={sourceRefreshToken}
              />
            )}
            {view === "tools" && (
              <div className="settings-tools">
                <div className="settings-tools__switcher">
                  <button
                    type="button"
                    className={toolsView === "mcp" ? "is-active" : ""}
                    onClick={() => setToolsView("mcp")}
                  >
                    MCP Servers
                  </button>
                  <button
                    type="button"
                    className={toolsView === "function" ? "is-active" : ""}
                    onClick={() => setToolsView("function")}
                  >
                    Custom Functions
                  </button>
                </div>
                {toolsView === "mcp" && (
                  <McpCatalogPanel open={true} onClose={() => undefined} embedded />
                )}
                {toolsView === "function" && (
                  <FunctionsPanel open={true} onClose={() => undefined} embedded />
                )}
              </div>
            )}
            {view === "persona" && (
              <div className="settings-persona">
                <PersonaBadge />
                <SkillBadge />
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function ChatLayout({ persistentAttachments, setPersistentAttachments, sourceRefreshToken, user, onSignOut }: {
  persistentAttachments: Attachment[];
  setPersistentAttachments: (attachments: Attachment[]) => void;
  sourceRefreshToken: number;
  user: User;
  onSignOut: () => void;
}) {
  const { activeSessionId, sidebarOpen, setSidebarOpen, messages } = useChatContext();
  const toast = useToast();
  const [dark, toggleDark] = useDarkMode();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const dashboardArtifacts = useMemo(() => findDashboardArtifacts(messages), [messages]);
  const latestDashboard =
    dashboardArtifacts.length > 0 ? dashboardArtifacts[dashboardArtifacts.length - 1] : null;
  const [selectedDashboardKey, setSelectedDashboardKey] = useState<string | null>(null);
  const [dismissedDashboardKey, setDismissedDashboardKey] = useState<string | null>(null);
  const [isDashboardMaximized, setIsDashboardMaximized] = useState(false);
  const previousLatestDashboardKeyRef = useRef<string | null>(null);
  const latestDashboardKey = latestDashboard?.key ?? null;
  const selectedDashboard = selectedDashboardKey
    ? dashboardArtifacts.find((artifact) => artifact.key === selectedDashboardKey) ?? null
    : null;
  const activeDashboard = selectedDashboard ?? latestDashboard;
  const activeDashboardKey = activeDashboard?.key ?? null;
  const showDashboard =
    activeDashboard !== null &&
    activeDashboardKey !== null &&
    activeDashboardKey !== dismissedDashboardKey;

  useEffect(() => {
    if (latestDashboardKey && previousLatestDashboardKeyRef.current !== latestDashboardKey) {
      previousLatestDashboardKeyRef.current = latestDashboardKey;
      setSelectedDashboardKey(null);
      setDismissedDashboardKey(null);
    } else if (!latestDashboardKey) {
      previousLatestDashboardKeyRef.current = null;
      setSelectedDashboardKey(null);
      setDismissedDashboardKey(null);
    }
  }, [latestDashboardKey]);

  useEffect(() => {
    if (!showDashboard) setIsDashboardMaximized(false);
  }, [showDashboard]);

  useEffect(() => {
    if (!activeSessionId) {
      setPersistentAttachments([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const response = await apiFetch(apiPath(`/chat/sources/${encodeURIComponent(activeSessionId)}`));
        const items = await parseJsonResponse<SourceItem[]>(response);
        if (!cancelled) {
          setPersistentAttachments(items.map(sourceToAttachment).filter(Boolean) as Attachment[]);
        }
      } catch (error) {
        if (!cancelled) {
          setPersistentAttachments([]);
          toast.show(`Could not load artifacts: ${readErrorMessage(error)}`, "error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeSessionId, sourceRefreshToken, setPersistentAttachments, toast]);

  const handleOpenDashboard = useCallback(
    (artifact: DashboardArtifact) => {
      setSelectedDashboardKey(artifact.key === latestDashboardKey ? null : artifact.key);
      setDismissedDashboardKey(null);
    },
    [latestDashboardKey],
  );

  const renderDashboardSurfaceFooter = useCallback<SurfaceFooterRenderer>(
    ({ message, surface }) => {
      const surfaceArtifacts = dashboardArtifactsForSurface(message, surface);
      if (surfaceArtifacts.length === 0) return null;
      return (
        <div className="dashboard-artifact-open-row">
          {surfaceArtifacts.map((artifact) => {
            const isActive = artifact.key === activeDashboardKey && showDashboard;
            return (
              <button
                key={artifact.key}
                type="button"
                className={`dashboard-artifact-open${isActive ? " dashboard-artifact-open--active" : ""}`}
                onClick={() => handleOpenDashboard(artifact)}
                aria-label={`Open ${artifact.title} in artifact panel`}
                title="Open in artifact panel"
              >
                <svg
                  aria-hidden="true"
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <rect x="3" y="4" width="18" height="16" rx="2" />
                  <path d="M9 4v16" />
                  <path d="M13 9h4" />
                  <path d="M13 13h4" />
                </svg>
                <span>Open</span>
              </button>
            );
          })}
        </div>
      );
    },
    [activeDashboardKey, handleOpenDashboard, showDashboard],
  );

  return (
    <div className={`chat-layout${showDashboard && isDashboardMaximized ? " chat-layout--artifact-maximized" : ""}`}>
      <div className={`lci-mini-sidebar${sidebarOpen ? "" : " lci-mini-sidebar--collapsed"}`}>
        {sidebarOpen ? (
          <>
            <div className="lci-mini-sidebar__history">
              <SessionSidebar />
            </div>
            <div className="lci-mini-sidebar__footer">
              <SidebarSettingsButton onClick={() => setSettingsOpen(true)} />
            </div>
          </>
        ) : (
          <button
            type="button"
            className="sidebar-reopen"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open sidebar"
            title="Open sidebar"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M9 18 15 12 9 6" />
            </svg>
          </button>
        )}
      </div>
      <div className="chat-layout__main">
        <ChatPanel
          title="General Chat"
          suggestions={SUGGESTIONS}
          placeholder="Ask anything, add sources, generate a dashboard, or discover useful links..."
          greeting="Welcome to General Chat"
          persistentAttachments={persistentAttachments}
          acceptedFileTypes={SOURCE_ACCEPT}
          onAttachmentError={(message) => toast.show(message, "error")}
          onTranscribe={transcribeAudio}
          renderSurfaceFooter={renderDashboardSurfaceFooter}
          headerRight={
            <div className="chat-header-actions">
              <span className="auth-user" title={user.email ?? user.displayName ?? user.uid}>
                {user.email ?? user.displayName ?? "Signed in"}
              </span>
              <button type="button" className="auth-signout" onClick={onSignOut}>
                Sign out
              </button>
              <button
                type="button"
                className="theme-toggle"
                onClick={toggleDark}
                title={dark ? "Switch to light mode" : "Switch to dark mode"}
                aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
              >
                <ThemeIcon dark={dark} />
              </button>
            </div>
          }
        />
      </div>
      {showDashboard && activeDashboard && (
        <DashboardArtifactPanel
          artifact={activeDashboard}
          isMaximized={isDashboardMaximized}
          onToggleMaximized={() => setIsDashboardMaximized((value) => !value)}
          onClose={() => setDismissedDashboardKey(activeDashboardKey)}
        />
      )}
      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        sessionId={activeSessionId}
        sourceRefreshToken={sourceRefreshToken}
        onAttachmentsChange={setPersistentAttachments}
      />
    </div>
  );
}

function ChatShell({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const toast = useToast();
  const [persistentAttachments, setPersistentAttachments] = useState<Attachment[]>([]);
  const [sourceRefreshToken, setSourceRefreshToken] = useState(0);
  const getAuthToken = useCallback(() => user.getIdToken(), [user]);

  const chatConfig = useMemo<ChatConfig>(
    () => ({
      streamUrl: STREAM_URL,
      actionUrl: apiPath("/chat/action"),
      sessionsUrl: apiPath("/sessions"),
      getAuthToken,
      uploadFile: async (file: File, options: AttachmentUploadOptions) => {
        const sessionId = options.sessionId;
        if (!sessionId) throw new Error("A chat session is required before uploading files.");
        const attachment = await uploadComposerAttachment(
          file,
          sessionId,
          options.onProgress ?? (() => {}),
        );
        setSourceRefreshToken((value) => value + 1);
        return attachment;
      },
      onUploadSuccess: (_localId: string, attachment: { name: string }) => {
        toast.show(`Uploaded: ${attachment.name}`, "success");
      },
      onUploadError: (file: { name: string }, error: unknown) => {
        toast.show(`Upload failed for ${file.name}: ${readErrorMessage(error)}`, "error");
      },
      dashboardActions: {
        publish: async (viewModel: unknown) => {
          const response = await apiFetch(apiPath("/dashboard/publish"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ viewModel }),
          });
          if (!response.ok) throw new Error(`Publish failed: ${response.status}`);
          return (await response.json()) as { url: string };
        },
        exportGrafana: async (viewModel: unknown) => {
          const response = await apiFetch(apiPath("/dashboard/export/grafana"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ viewModel }),
          });
          try {
            return await parseJsonResponse<Record<string, unknown>>(response);
          } catch (error) {
            throw new Error(`Export failed: ${readErrorMessage(error)}`);
          }
        },
        deployGrafana: async (viewModel: unknown) => {
          const response = await apiFetch(apiPath("/dashboard/deploy/grafana"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ viewModel }),
          });
          try {
            return await parseJsonResponse<{ url: string }>(response);
          } catch (error) {
            throw new Error(`Deploy failed: ${readErrorMessage(error)}`);
          }
        },
        exportPdf: async (viewModel: unknown) => {
          const response = await apiFetch(apiPath("/dashboard/export/pdf"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ viewModel }),
          });
          if (!response.ok) throw new Error(`PDF export failed: ${response.status}`);
          return await response.blob();
        },
        loadHtml: async (url: string) => {
          const response = await apiFetch(apiPath(url));
          if (!response.ok) throw new Error(`Load failed: ${response.status}`);
          return response.text();
        },
      },
    }),
    [getAuthToken, toast],
  );

  return (
    <ChatProvider config={chatConfig}>
      <ErrorBoundary region="chat">
        <ChatLayout
          persistentAttachments={persistentAttachments}
          setPersistentAttachments={setPersistentAttachments}
          sourceRefreshToken={sourceRefreshToken}
          user={user}
          onSignOut={onSignOut}
        />
      </ErrorBoundary>
    </ChatProvider>
  );
}

type AuthzState = "checking" | "authorized" | "denied" | "error";

function AuthGate() {
  const toast = useToast();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [authz, setAuthz] = useState<AuthzState>("checking");
  const [probeNonce, setProbeNonce] = useState(0);

  useEffect(() => {
    if (!isFirebaseConfigured()) {
      setError("Firebase is not configured for this deployment.");
      setIsLoading(false);
      return;
    }

    const auth = getFirebaseAuth();
    return onAuthStateChanged(
      auth,
      (nextUser) => {
        setUser(nextUser);
        setIsLoading(false);
      },
      (authError) => {
        setError(authError.message);
        setIsLoading(false);
      },
    );
  }, []);

  useEffect(() => {
    if (!user) {
      setAuthTokenProvider(null);
      return;
    }
    setAuthTokenProvider(() => user.getIdToken());
    return () => setAuthTokenProvider(null);
  }, [user]);

  // Probe a protected endpoint to confirm this signed-in account is on the
  // backend allowlist. Firebase admits any Google account, so authorization is
  // decided server-side: 200 = allowed, 403 = not on the allowlist, anything
  // else (network/401/5xx) = could not verify -> offer a retry.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    setAuthz("checking");
    (async () => {
      try {
        const token = await user.getIdToken();
        const response = await fetch(apiPath("/persona"), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (cancelled) return;
        if (response.ok) {
          setAuthz("authorized");
        } else if (response.status === 403) {
          setAuthz("denied");
        } else {
          setAuthz("error");
        }
      } catch {
        if (!cancelled) setAuthz("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, probeNonce]);

  const handleSignIn = async () => {
    setError("");
    try {
      await signInWithPopup(getFirebaseAuth(), googleProvider);
    } catch (signInError) {
      setError(readErrorMessage(signInError));
    }
  };

  const handleSignOut = async () => {
    try {
      await signOut(getFirebaseAuth());
      toast.show("Signed out", "success");
    } catch (signOutError) {
      toast.show(`Sign out failed: ${readErrorMessage(signOutError)}`, "error");
    }
  };

  if (isLoading) {
    return (
      <div className="auth-screen">
        <div className="auth-panel">
          <div className="auth-title">General Chat</div>
          <div className="auth-copy">Checking authentication...</div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="auth-screen">
        <div className="auth-panel">
          <div className="auth-title">General Chat</div>
          <div className="auth-copy">Sign in with your approved Google account to continue.</div>
          {error && <div className="auth-error">{error}</div>}
          <button type="button" className="auth-primary" onClick={() => void handleSignIn()}>
            Sign in with Google
          </button>
        </div>
      </div>
    );
  }

  if (authz === "checking") {
    return (
      <div className="auth-screen">
        <div className="auth-panel">
          <div className="auth-title">General Chat</div>
          <div className="auth-copy">Checking access...</div>
        </div>
      </div>
    );
  }

  if (authz === "denied") {
    return (
      <div className="auth-screen">
        <div className="auth-panel">
          <div className="auth-title">Access not authorized</div>
          <div className="auth-copy">
            {user.email ?? "This account"} is not approved for this deployment. Ask an administrator
            to add your email to the allowlist, then sign in again.
          </div>
          <button type="button" className="auth-primary" onClick={() => void handleSignOut()}>
            Sign out
          </button>
        </div>
      </div>
    );
  }

  if (authz === "error") {
    return (
      <div className="auth-screen">
        <div className="auth-panel">
          <div className="auth-title">General Chat</div>
          <div className="auth-copy">Could not verify access. Check your connection and try again.</div>
          <button type="button" className="auth-primary" onClick={() => setProbeNonce((value) => value + 1)}>
            Retry
          </button>
          <button type="button" className="auth-signout" onClick={() => void handleSignOut()}>
            Sign out
          </button>
        </div>
      </div>
    );
  }

  return <ChatShell user={user} onSignOut={() => void handleSignOut()} />;
}

export default function App() {
  return (
    <ToastProvider>
      <AuthGate />
    </ToastProvider>
  );
}
