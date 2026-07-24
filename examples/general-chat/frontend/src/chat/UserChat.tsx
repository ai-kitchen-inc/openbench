/** User-facing chat shell (ported from the legacy general-chat ChatShell +
 * ChatLayout): capability-gated composer attachments, per-session sources,
 * dashboard artifact side panel, and the admin-curated global sources
 * drawer. */
import {
  ChatPanel,
  ChatProvider,
  SessionSidebar,
  useChatContext,
  type Attachment,
  type AttachmentUploadOptions,
  type ChatConfig,
  type SurfaceFooterRenderer,
} from "@openbench/chat-ui";
import type { User } from "firebase/auth";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Me } from "../account/api";
import { apiFetch, apiPath, getLocalRole, setLocalRole, transcribeAudio } from "../api";
import { BookIcon } from "../brand/icons";
import { ErrorBoundary } from "../ErrorBoundary";
import { FunctionsPanel } from "../functions/FunctionsPanel";
import { APP_NAME, COMMON, LOCAL_ROLE } from "../i18n/id";
import { McpCatalogPanel } from "../mcp-catalog/McpCatalogPanel";
import { ThemeIcon, useDarkMode } from "../theme";
import { useToast } from "../Toast";
import {
  DashboardArtifactPanel,
  dashboardArtifactsForSurface,
  findDashboardArtifacts,
  type DashboardArtifact,
} from "./dashboard";
import { SourcePanel } from "./SourcePanel";
import { SourcesDrawer } from "./SourcesDrawer";
import {
  parseJsonResponse,
  readErrorMessage,
  SOURCE_ACCEPT,
  sourceToAttachment,
  uploadComposerAttachment,
  type SourceItem,
} from "./uploads";

const STREAM_URL = apiPath("/awp");

const SUGGESTIONS = [
  "Apa saja yang dicakup oleh sumber pengetahuan?",
  "Ringkas isi basis pengetahuan",
  "Bantu saya memikirkan masalah ini",
  "Bandingkan beberapa opsi beserta kelebihan-kekurangannya",
  "Buat dashboard dari spreadsheet saya",
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

function BadgeSkeleton({ title, rows }: { title: string; rows: number }) {
  return (
    <div className="badge-skeleton" aria-busy="true" aria-label={`Memuat ${title}`}>
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
    return <div className="persona-badge persona-badge--empty">Belum ada persona yang dimuat</div>;
  }

  return (
    <div className="persona-badge">
      <div className="persona-badge__title">Persona dimuat dari soul/</div>
      <div className="persona-badge__row">
        <span>SOUL.md</span>
        <span>{persona.soul_chars} karakter</span>
      </div>
      <div className="persona-badge__row">
        <span>STYLE.md</span>
        <span>{persona.style_chars} karakter</span>
      </div>
      <div className="persona-badge__row">
        <span>AGENTS.md</span>
        <span>{persona.agents_chars} karakter</span>
      </div>
      <div className="persona-badge__row persona-badge__row--total">
        <span>Total prompt</span>
        <span>{persona.total_chars} karakter</span>
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

  if (isLoading) return <BadgeSkeleton title="Keahlian" rows={3} />;
  if (!data) return null;
  if (!data.loaded || data.skills.length === 0) {
    return <div className="skill-badge skill-badge--empty">Belum ada keahlian yang dimuat</div>;
  }

  return (
    <div className="skill-badge">
      <div className="skill-badge__title">Keahlian dimuat ({data.skills.length})</div>
      {data.skills.map((skill) => (
        <div key={skill.name} className="skill-badge__item">
          <div className="skill-badge__name">
            {skill.name} <span className="skill-badge__version">v{skill.version}</span>
          </div>
        </div>
      ))}
      {data.summary && (
        <div className="persona-badge__row persona-badge__row--total">
          <span>Konteks keahlian</span>
          <span>{data.summary.context_chars} karakter</span>
        </div>
      )}
    </div>
  );
}

type SettingsView = "artifact" | "tools" | "persona";
type ToolsView = "menu" | "mcp" | "function";

function SidebarSettingsButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="sidebar-settings-button"
      onClick={onClick}
      aria-label="Buka Pengaturan"
    >
      <span className="sidebar-settings-button__icon" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1A2 2 0 1 1 4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.3 7A2 2 0 1 1 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3h.1A1.7 1.7 0 0 0 10 3V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1A2 2 0 1 1 19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1A1.7 1.7 0 0 0 21 10h.1a2 2 0 1 1 0 4H21a1.7 1.7 0 0 0-1.6 1Z" />
        </svg>
      </span>
      <span>Pengaturan</span>
    </button>
  );
}

function SettingsDialog({
  open,
  me,
  onClose,
  sessionId,
  sourceRefreshToken,
  onAttachmentsChange,
  onOpenMcp,
  onOpenFunctions,
}: {
  open: boolean;
  me: Me;
  onClose: () => void;
  sessionId: string | null;
  sourceRefreshToken: number;
  onAttachmentsChange: (attachments: Attachment[]) => void;
  onOpenMcp: () => void;
  onOpenFunctions: () => void;
}) {
  const showSources = me.capabilities.session_sources;
  const showMcp = me.capabilities.mcp_management;
  const showFunctions = me.capabilities.custom_functions;
  const showTools = showMcp || showFunctions;
  const defaultView: SettingsView = showSources ? "artifact" : showTools ? "tools" : "persona";
  const [view, setView] = useState<SettingsView>(defaultView);
  const [toolsView, setToolsView] = useState<ToolsView>("menu");

  useEffect(() => {
    if (open) {
      setView(defaultView);
      setToolsView("menu");
    }
  }, [open, defaultView]);

  if (!open) return null;

  return (
    <div className="settings-dialog" role="presentation" onMouseDown={onClose}>
      <div
        className="settings-dialog__panel"
        role="dialog"
        aria-modal="true"
        aria-label="Pengaturan"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="settings-dialog__header">
          <div>
            <h2>Pengaturan</h2>
            <p>Kelola sumber, perangkat, dan persona.</p>
          </div>
          <button type="button" className="settings-dialog__close" onClick={onClose} aria-label="Tutup pengaturan">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </div>
        <div className="settings-dialog__body">
          <nav className="settings-dialog__nav" aria-label="Bagian pengaturan">
            {showSources && (
              <button type="button" className={view === "artifact" ? "is-active" : ""} onClick={() => setView("artifact")}>
                Sumber
              </button>
            )}
            {showTools && (
              <button type="button" className={view === "tools" ? "is-active" : ""} onClick={() => setView("tools")}>
                Perangkat
              </button>
            )}
            <button type="button" className={view === "persona" ? "is-active" : ""} onClick={() => setView("persona")}>
              Persona
            </button>
          </nav>
          <section className="settings-dialog__content">
            {view === "artifact" && showSources && (
              <SourcePanel
                sessionId={sessionId}
                onAttachmentsChange={onAttachmentsChange}
                refreshToken={sourceRefreshToken}
              />
            )}
            {view === "tools" && showTools && (
              <div className="settings-tools">
                <div className="settings-tools__switcher">
                  {showMcp && (
                    <button
                      type="button"
                      className={toolsView === "mcp" ? "is-active" : ""}
                      onClick={() => setToolsView("mcp")}
                    >
                      MCP
                    </button>
                  )}
                  {showFunctions && (
                    <button
                      type="button"
                      className={toolsView === "function" ? "is-active" : ""}
                      onClick={() => setToolsView("function")}
                    >
                      Fungsi
                    </button>
                  )}
                </div>
                {toolsView === "menu" && (
                  <div className="settings-tools__empty">Pilih MCP atau Fungsi untuk mengelola perangkat yang tersedia.</div>
                )}
                {toolsView === "mcp" && showMcp && (
                  <div className="settings-tools__panel">
                    <button type="button" className="settings-tools__open" onClick={onOpenMcp}>
                      Buka pengelola server MCP
                    </button>
                  </div>
                )}
                {toolsView === "function" && showFunctions && (
                  <div className="settings-tools__panel">
                    <button type="button" className="settings-tools__open" onClick={onOpenFunctions}>
                      Buka pengelola fungsi kustom
                    </button>
                  </div>
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

function ChatLayout({
  me,
  persistentAttachments,
  setPersistentAttachments,
  sourceRefreshToken,
  user,
  onSignOut,
}: {
  me: Me;
  persistentAttachments: Attachment[];
  setPersistentAttachments: (attachments: Attachment[]) => void;
  sourceRefreshToken: number;
  user: User | null;
  onSignOut: () => void;
}) {
  const { activeSessionId, sidebarOpen, setSidebarOpen, messages } = useChatContext();
  const toast = useToast();
  const [dark, toggleDark] = useDarkMode();
  const [mcpCatalogOpen, setMcpCatalogOpen] = useState(false);
  const [functionsOpen, setFunctionsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sourcesDrawerOpen, setSourcesDrawerOpen] = useState(false);
  const canUseSessionSources = me.capabilities.session_sources;
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
    if (!activeSessionId || !canUseSessionSources) {
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
          toast.show(`Gagal memuat artefak: ${readErrorMessage(error)}`, "error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeSessionId, canUseSessionSources, sourceRefreshToken, setPersistentAttachments, toast]);

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
                aria-label={`Buka ${artifact.title} di panel artefak`}
                title="Buka di panel artefak"
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
                <span>Buka</span>
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
            aria-label="Buka bilah samping"
            title="Buka bilah samping"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M9 18 15 12 9 6" />
            </svg>
          </button>
        )}
      </div>
      <div className="chat-layout__main">
        <ChatPanel
          title={APP_NAME}
          suggestions={SUGGESTIONS}
          placeholder="Ketik pertanyaan, tambahkan sumber, atau minta dibuatkan dashboard..."
          greeting={`Selamat datang di ${APP_NAME}`}
          persistentAttachments={persistentAttachments}
          acceptedFileTypes={SOURCE_ACCEPT}
          onAttachmentError={(message) => toast.show(message, "error")}
          onTranscribe={me.capabilities.attachments ? transcribeAudio : undefined}
          renderSurfaceFooter={renderDashboardSurfaceFooter}
          headerRight={
            <div className="chat-header-actions">
              <button
                type="button"
                className="panel-button"
                onClick={() => setSourcesDrawerOpen(true)}
              >
                <BookIcon size={14} />
                Sumber
              </button>
              <span className="auth-user" title={me.email || user?.email || "lokal"}>
                {me.email || user?.email || "Sudah masuk"}
              </span>
              <button
                type="button"
                className="theme-toggle"
                onClick={toggleDark}
                title={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
                aria-label={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
              >
                <ThemeIcon dark={dark} />
              </button>
              {me.authDisabled && getLocalRole() === "user" && (
                <button
                  type="button"
                  className="auth-signout"
                  onClick={() => {
                    setLocalRole(null);
                    window.location.reload();
                  }}
                >
                  {LOCAL_ROLE.backToAdmin}
                </button>
              )}
              <button type="button" className="auth-signout" onClick={onSignOut}>
                {COMMON.signOut}
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
      <SourcesDrawer open={sourcesDrawerOpen} onClose={() => setSourcesDrawerOpen(false)} />
      <SettingsDialog
        open={settingsOpen}
        me={me}
        onClose={() => setSettingsOpen(false)}
        sessionId={activeSessionId}
        sourceRefreshToken={sourceRefreshToken}
        onAttachmentsChange={setPersistentAttachments}
        onOpenMcp={() => setMcpCatalogOpen(true)}
        onOpenFunctions={() => setFunctionsOpen(true)}
      />
      {me.capabilities.mcp_management && (
        <McpCatalogPanel open={mcpCatalogOpen} onClose={() => setMcpCatalogOpen(false)} />
      )}
      {me.capabilities.custom_functions && (
        <FunctionsPanel open={functionsOpen} onClose={() => setFunctionsOpen(false)} />
      )}
    </div>
  );
}

export function UserChat({
  me,
  user,
  onSignOut,
}: {
  me: Me;
  user: User | null;
  onSignOut: () => void;
}) {
  const toast = useToast();
  const [persistentAttachments, setPersistentAttachments] = useState<Attachment[]>([]);
  const [sourceRefreshToken, setSourceRefreshToken] = useState(0);
  const getAuthToken = useCallback(
    async () => (user ? await user.getIdToken() : null),
    [user],
  );
  const allowAttachments = me.capabilities.attachments;

  const chatConfig = useMemo<ChatConfig>(() => {
    const config: ChatConfig = {
      streamUrl: STREAM_URL,
      actionUrl: apiPath("/chat/action"),
      sessionsUrl: apiPath("/sessions"),
      getAuthToken,
      dashboardActions: {
        publish: async (viewModel: unknown) => {
          const response = await apiFetch(apiPath("/dashboard/publish"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ viewModel }),
          });
          if (!response.ok) throw new Error(`Publikasi gagal: ${response.status}`);
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
            throw new Error(`Ekspor gagal: ${readErrorMessage(error)}`);
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
            throw new Error(`Deploy gagal: ${readErrorMessage(error)}`);
          }
        },
        exportPdf: async (viewModel: unknown) => {
          const response = await apiFetch(apiPath("/dashboard/export/pdf"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ viewModel }),
          });
          if (!response.ok) throw new Error(`Ekspor PDF gagal: ${response.status}`);
          return await response.blob();
        },
        loadHtml: async (url: string) => {
          const response = await apiFetch(apiPath(url));
          if (!response.ok) throw new Error(`Gagal memuat: ${response.status}`);
          return response.text();
        },
      },
    };

    // uploadFile only exists when the account may attach files — omitting the
    // key hides the composer attach control entirely.
    if (allowAttachments) {
      config.uploadFile = async (file: File, options: AttachmentUploadOptions) => {
        const sessionId = options.sessionId;
        if (!sessionId) throw new Error("Sesi chat diperlukan sebelum mengunggah berkas.");
        const attachment = await uploadComposerAttachment(
          file,
          sessionId,
          options.onProgress ?? (() => {}),
        );
        setSourceRefreshToken((value) => value + 1);
        return attachment;
      };
      config.onUploadSuccess = (_localId: string, attachment: { name: string }) => {
        toast.show(`Berhasil diunggah: ${attachment.name}`, "success");
      };
      config.onUploadError = (file: { name: string }, error: unknown) => {
        toast.show(`Gagal mengunggah ${file.name}: ${readErrorMessage(error)}`, "error");
      };
    }

    return config;
  }, [allowAttachments, getAuthToken, toast]);

  return (
    <ChatProvider config={chatConfig}>
      <ErrorBoundary region="percakapan">
        <ChatLayout
          me={me}
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
