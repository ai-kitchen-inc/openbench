import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { XIcon } from "../brand/icons";
import { useToast } from "../Toast";
import {
  discoverServer,
  deleteToolHiveWorkload,
  getServer,
  getToolHiveStatus,
  importMCPConfig,
  importRunningToolHiveWorkloads,
  listServers,
  listToolHiveRegistryServers,
  listToolHiveWorkloads,
  removeServer,
  restartToolHiveWorkload,
  startToolHiveWorkload,
  stopToolHiveWorkload,
  toggleServer,
  toggleTool,
} from "./api";
import { filterServers, type RegistryFilters, type SortMode, type StatusFilter } from "./filtering";
import type {
  MCPDiscoveredTool,
  MCPRegistryPayload,
  MCPSecretMetadata,
  RegisteredMCPServer,
  ToolHiveRegistryServer,
  ToolHiveStatus,
  ToolHiveWorkload,
} from "./types";

const EXAMPLE_CONFIG = `{
  "mcpServers": {
    "custom_docker": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "mcp/playwright"
      ]
    }
  }
}`;

const DEFAULT_FILTERS: RegistryFilters = {
  query: "",
  status: "all",
  sort: "name",
};

const TOOLHIVE_DOC_SERVER = "toolhive-doc-mcp";

function readErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

type SecretRow = {
  id: string;
  key: string;
  value: string;
};

function buildSecretPayload(rows: SecretRow[]): Record<string, string> | undefined {
  const payload: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    const value = row.value.trim();
    if (!key || !value) continue;
    payload[key] = value;
  }
  return Object.keys(payload).length ? payload : undefined;
}

function toolHiveModeLabel(status: ToolHiveStatus | null): string {
  if (!status) return "belum diperiksa";
  if (status.managementMode === "api") return "API";
  if (status.managementMode === "ui-cli") return "ToolHive UI CLI";
  if (status.managementMode === "cli") return "CLI";
  return "tidak tersedia";
}

function Dialog({
  title,
  onClose,
  children,
  initialFocusRef,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const target = initialFocusRef?.current ?? panelRef.current;
    target?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [initialFocusRef, onClose]);

  return (
    <div className="mcp-dialog" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        className="mcp-dialog__panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={panelRef}
        tabIndex={-1}
      >
        <div className="mcp-dialog__header">
          <h2>{title}</h2>
          <button type="button" className="mcp-icon-btn" onClick={onClose} aria-label="Tutup dialog">
            <XIcon size={14} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function ImportDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (payload: MCPRegistryPayload) => void;
}) {
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [config, setConfig] = useState(EXAMPLE_CONFIG);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const nextSecretId = useRef(2);
  const [secretRows, setSecretRows] = useState<SecretRow[]>([{ id: "secret-1", key: "", value: "" }]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError("");
    try {
      const payload = await importMCPConfig({
        config,
        secrets: buildSecretPayload(secretRows),
      });
      onImported(payload);
      onClose();
    } catch (error) {
      setError(readErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog title="Tambah Server MCP" onClose={onClose} initialFocusRef={inputRef}>
      <form className="mcp-dialog__body" onSubmit={(event) => void handleSubmit(event)}>
        <label className="mcp-field">
          <span>Konfigurasi JSON MCP</span>
          <textarea
            ref={inputRef}
            value={config}
            onChange={(event) => setConfig(event.target.value)}
            rows={14}
            spellCheck={false}
            required
          />
        </label>
        <div className="mcp-warning">
          Validasi hanya memeriksa bentuk JSON. OpenBench menjalankan server MCP berbasis perintah hanya saat Anda memuat alat atau menggunakan chat.
        </div>
        <div className="mcp-config-list">
          <h3>Env Docker</h3>
          <div className="mcp-warning">
            Nilai env Docker yang dimasukkan di sini atau ditempel pada JSON <code>env</code> dienkripsi sebelum disimpan dan hanya disuntikkan saat runtime. Gunakan <code>{'${ENV_VAR}'}</code> untuk membaca dari environment lokal Anda.
          </div>
          <div className="mcp-config-list">
            {secretRows.map((row) => (
              <div key={row.id} className="mcp-detail-grid mcp-detail-grid--forms">
                <label className="mcp-field">
                  <span>Kunci</span>
                  <input
                    value={row.key}
                    placeholder="GRAFANA_API_KEY"
                    onChange={(event) =>
                      setSecretRows((current) =>
                        current.map((item) =>
                          item.id === row.id ? { ...item, key: event.target.value } : item,
                        ),
                      )
                    }
                  />
                </label>
                <label className="mcp-field">
                  <span>Nilai</span>
                  <input
                    type="password"
                    value={row.value}
                    autoComplete="off"
                    placeholder="Nilai env Docker"
                    onChange={(event) =>
                      setSecretRows((current) =>
                        current.map((item) =>
                          item.id === row.id ? { ...item, value: event.target.value } : item,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  className="mcp-btn"
                  onClick={() =>
                    setSecretRows((current) => current.filter((item) => item.id !== row.id))
                  }
                >
                  Hapus
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="mcp-btn"
            onClick={() => {
              const id = `secret-${nextSecretId.current}`;
              nextSecretId.current += 1;
              setSecretRows((current) => [...current, { id, key: "", value: "" }]);
            }}
          >
            Tambah Env
          </button>
        </div>
        {error && (
          <div className="mcp-state mcp-state--error" role="alert">
            {error}
          </div>
        )}
        <div className="mcp-dialog__actions">
          <button type="button" className="mcp-btn" onClick={onClose}>
            Batal
          </button>
          <button type="submit" className="mcp-btn mcp-btn--primary" disabled={!config.trim() || isSubmitting}>
            {isSubmitting ? "Mendaftarkan..." : "Daftarkan Server"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function statusClass(server: RegisteredMCPServer): string {
  if (!server.enabled) return "";
  if (server.status === "failed" || server.status === "unavailable") return " mcp-pill--error";
  if (server.status === "running" || server.status === "enabled" || server.status === "registered") return " mcp-pill--success";
  return "";
}

function providerLabel(server: RegisteredMCPServer): string {
  return server.providerKind ?? server.provider_kind ?? server.sourceType ?? server.source_type ?? server.source ?? "manual";
}

function parameterSummary(schema: Record<string, unknown>): string {
  const properties = schema.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) {
    return "Tanpa parameter";
  }
  const required = Array.isArray(schema.required) ? schema.required : [];
  const parts = Object.entries(properties as Record<string, Record<string, unknown>>).map(([name, value]) => {
    const type = typeof value?.type === "string" ? value.type : "value";
    return `${name}: ${type}${required.includes(name) ? " wajib" : ""}`;
  });
  return parts.length ? parts.join(", ") : "Tanpa parameter";
}

function ConfigPreview({ config }: { config: Record<string, unknown> }) {
  return <pre className="mcp-config-preview">{JSON.stringify(config, null, 2)}</pre>;
}

function serverSecrets(server: RegisteredMCPServer): MCPSecretMetadata[] {
  return server.secretMetadata ?? server.secret_metadata ?? server.secrets ?? [];
}

function buildUrlConfig(name: string, url: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        [name]: { url },
      },
    },
    null,
    2,
  );
}

function ToolHiveSection({
  onImported,
}: {
  onImported: (payload: MCPRegistryPayload) => void;
}) {
  const toast = useToast();
  const [status, setStatus] = useState<ToolHiveStatus | null>(null);
  const [workloads, setWorkloads] = useState<ToolHiveWorkload[]>([]);
  const [registry, setRegistry] = useState<ToolHiveRegistryServer[]>([]);
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState(TOOLHIVE_DOC_SERVER);
  const [workloadName, setWorkloadName] = useState("");
  const [remoteUrl, setRemoteUrl] = useState("");
  const [directUrl, setDirectUrl] = useState("");
  const [directName, setDirectName] = useState("toolhive");
  const [allowRemote, setAllowRemote] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const nextStatus = await getToolHiveStatus();
      setStatus(nextStatus);
      if (!nextStatus.available) {
        setWorkloads([]);
        setRegistry([]);
        return;
      }

      const [workloadsResult, registryResult] = await Promise.allSettled([
        listToolHiveWorkloads(),
        listToolHiveRegistryServers(),
      ]);
      if (workloadsResult.status === "fulfilled") {
        setWorkloads(workloadsResult.value.workloads);
      } else {
        setWorkloads([]);
        setError(readErrorMessage(workloadsResult.reason));
      }
      if (registryResult.status === "fulfilled") {
        setRegistry(registryResult.value.servers);
      } else {
        setRegistry([]);
      }
    } catch (error) {
      setStatus(null);
      setWorkloads([]);
      setRegistry([]);
      setError(readErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleImportWorkload = async (name: string) => {
    setIsMutating(true);
    try {
      const payload = await importRunningToolHiveWorkloads([name]);
      onImported(payload);
      toast.show("Server ToolHive berhasil diimpor", "success");
    } catch (error) {
      toast.show(`Gagal menambahkan server ToolHive: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  };

  const handleStart = async (startTarget: string, name?: string, remote = false) => {
    if (!startTarget.trim()) return;
    setIsMutating(true);
    try {
      const result = await startToolHiveWorkload({
        target: startTarget.trim(),
        name: name?.trim() || undefined,
        allowRemote: remote,
      });
      await load();
      await handleImportWorkload(result.workload.name);
      toast.show("Workload ToolHive dimulai", "success");
    } catch (error) {
      toast.show(`Gagal memulai workload ToolHive: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  };

  const handleRegisterUrl = async () => {
    const name = directName.trim() || "toolhive";
    const url = directUrl.trim();
    if (!url) return;
    setIsMutating(true);
    try {
      const payload = await importMCPConfig({ config: buildUrlConfig(name, url) });
      onImported(payload);
      setDirectUrl("");
      toast.show("URL ToolHive terdaftar", "success");
    } catch (error) {
      toast.show(`Gagal mendaftarkan URL ToolHive: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  };

  const handleWorkloadAction = async (action: "stop" | "restart" | "delete", name: string) => {
    const actionLabels = { stop: "penghentian", restart: "mulai ulang", delete: "penghapusan" } as const;
    if (action === "delete" && !window.confirm(`Hapus workload ToolHive ${name}? Tindakan ini menghentikan dan menghapus workload ToolHive, bukan hanya referensinya di OpenBench.`)) {
      return;
    }
    setIsMutating(true);
    try {
      if (action === "stop") await stopToolHiveWorkload(name);
      if (action === "restart") await restartToolHiveWorkload(name);
      if (action === "delete") await deleteToolHiveWorkload(name);
      await load();
      toast.show(`Permintaan ${actionLabels[action]} workload ToolHive terkirim`, "success");
    } catch (error) {
      toast.show(`Gagal ${actionLabels[action]} workload ToolHive: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  };

  const visibleRegistry = registry
    .filter((server) => {
      const haystack = `${server.name} ${server.title} ${server.description ?? ""} ${server.tools.join(" ")}`.toLowerCase();
      return haystack.includes(query.toLowerCase());
    })
    .slice(0, 8);

  return (
    <section className="mcp-section">
      <div className="mcp-section__header">
        <div>
          <h3>ToolHive MCP</h3>
          <p>
            {status?.available
              ? `${status.version ?? "ToolHive"} via ${toolHiveModeLabel(status)}`
              : "Gunakan server ToolHive UI di OpenBench"}
          </p>
        </div>
        <button type="button" className="mcp-btn" onClick={() => void load()} disabled={isLoading}>
          Segarkan Server Berjalan
        </button>
      </div>

      {isLoading && <div className="mcp-state">Memeriksa ToolHive...</div>}
      {!isLoading && error && (
        <div className="mcp-state mcp-state--error" role="alert">
          {error}
        </div>
      )}
      {!isLoading && status && !status.available && (
        <div className="mcp-warning">
          {status.setupHint || "Pasang ToolHive, verifikasi dengan thv version, lalu jalankan API lokal dengan thv serve."}
        </div>
      )}
      {!isLoading && status?.available && !status.apiAvailable && (
        <div className="mcp-warning">
          API ToolHive tidak berjalan. OpenBench tetap dapat mengimpor server berjalan melalui
          {status.uiCliDetected ? " CLI bawaan ToolHive UI" : " CLI ToolHive"}, tetapi penelusuran registry dan kontrol lokal memerlukan <code>thv serve</code>.
        </div>
      )}

      <div className="mcp-warning mcp-toolhive-companion">
        <strong>Kelola server di ToolHive UI</strong>
        <p>
          Mulai, konfigurasikan, dan periksa server MCP di aplikasi desktop ToolHive. Kemudian
          segarkan di sini dan impor server yang berjalan ke OpenBench untuk penemuan alat dan
          penggunaan chat.
        </p>
        <div className="mcp-links">
          <a href="https://docs.stacklok.com/toolhive/guides-ui/" target="_blank" rel="noreferrer">
            Panduan ToolHive UI
          </a>
          <a href="https://docs.stacklok.com/toolhive/guides-ui/client-configuration" target="_blank" rel="noreferrer">
            Salin URL server MCP
          </a>
        </div>
        {status?.cliPath && <code className="mcp-inline-code">CLI terdeteksi: {status.cliPath}</code>}
      </div>

      <div className="mcp-config-list">
        <h3>Server ToolHive Berjalan</h3>
        {workloads.length === 0 ? (
          <div className="mcp-state">Tidak ada server MCP ToolHive yang berjalan. Mulai lewat ToolHive UI, lalu segarkan.</div>
        ) : (
          <div className="mcp-catalog-list">
            {workloads.map((workload) => (
              <div key={workload.name} className="mcp-catalog-row">
                <div>
                  <strong>{workload.name}</strong>
                  <span>{workload.url || "URL proxy tidak ditemukan"}</span>
                  <div className="mcp-source-line">
                    <span className="mcp-pill">{workload.transport || "unknown"}</span>
                    <span className="mcp-pill">{workload.status}</span>
                  </div>
                </div>
                <div className="mcp-catalog-row__actions">
                  <button type="button" className="mcp-btn" onClick={() => void handleImportWorkload(workload.name)} disabled={isMutating || !workload.url}>
                    Impor ke OpenBench
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mcp-detail-grid mcp-detail-grid--forms">
        <label className="mcp-field">
          <span>URL MCP ToolHive yang disalin</span>
          <input value={directUrl} onChange={(event) => setDirectUrl(event.target.value)} placeholder="http://127.0.0.1:19767/mcp" />
        </label>
        <label className="mcp-field">
          <span>Nama server</span>
          <input value={directName} onChange={(event) => setDirectName(event.target.value)} />
        </label>
        <button type="button" className="mcp-btn" onClick={() => void handleRegisterUrl()} disabled={isMutating || !directUrl.trim()}>
          Daftarkan URL Tersalin
        </button>
      </div>

      <details className="mcp-advanced-controls">
        <summary>Kontrol lokal lanjutan</summary>
        <div className="mcp-advanced-controls__body">
          <div className="mcp-detail-grid mcp-detail-grid--forms">
            <label className="mcp-field">
              <span>Server registry</span>
              <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="toolhive-doc-mcp" />
            </label>
            <label className="mcp-field">
              <span>Nama workload</span>
              <input value={workloadName} onChange={(event) => setWorkloadName(event.target.value)} placeholder="Opsional" />
            </label>
            <button type="button" className="mcp-btn mcp-btn--primary" onClick={() => void handleStart(target, workloadName)} disabled={isMutating || !target.trim()}>
              Mulai Server Registry
            </button>
          </div>

          <div className="mcp-detail-grid mcp-detail-grid--forms">
            <label className="mcp-field">
              <span>URL MCP remote untuk diproksikan ToolHive</span>
              <input value={remoteUrl} onChange={(event) => setRemoteUrl(event.target.value)} placeholder="https://example.com/mcp" />
            </label>
            <label className="mcp-toggle mcp-toggle--field">
              <input type="checkbox" checked={allowRemote} onChange={() => setAllowRemote((current) => !current)} />
              <span>URL remote disetujui pengguna</span>
            </label>
            <button type="button" className="mcp-btn" onClick={() => void handleStart(remoteUrl, workloadName, allowRemote)} disabled={isMutating || !remoteUrl.trim()}>
              Mulai Proxy Remote
            </button>
          </div>

          {workloads.length > 0 && (
            <div className="mcp-config-list">
              <h3>Kontrol Workload</h3>
              <div className="mcp-catalog-list">
                {workloads.map((workload) => (
                  <div key={workload.name} className="mcp-catalog-row">
                    <div>
                      <strong>{workload.name}</strong>
                      <span>{workload.url || "URL proxy tidak ditemukan"}</span>
                    </div>
                    <div className="mcp-catalog-row__actions">
                      <button type="button" className="mcp-btn" onClick={() => void handleWorkloadAction("restart", workload.name)} disabled={isMutating}>
                        Mulai Ulang
                      </button>
                      <button type="button" className="mcp-btn" onClick={() => void handleWorkloadAction("stop", workload.name)} disabled={isMutating}>
                        Hentikan
                      </button>
                      <button type="button" className="mcp-btn" onClick={() => void handleWorkloadAction("delete", workload.name)} disabled={isMutating}>
                        Hapus
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mcp-config-list">
            <h3>Registry ToolHive</h3>
            <label className="mcp-search">
              <span>Cari registry ToolHive</span>
              <input value={query} type="search" placeholder="Cari server registry" onChange={(event) => setQuery(event.target.value)} />
            </label>
            {visibleRegistry.length === 0 ? (
              <div className="mcp-state">Belum ada server registry yang dimuat. Jalankan thv serve untuk menelusuri registry ToolHive.</div>
            ) : (
              <div className="mcp-catalog-list">
                {visibleRegistry.map((server) => (
                  <div key={server.name} className="mcp-catalog-row">
                    <div>
                      <strong>{server.title || server.name}</strong>
                      <span>{server.description || server.name}</span>
                      <div className="mcp-source-line">
                        <span className="mcp-pill">{server.transport || "transport"}</span>
                        {server.tier && <span className="mcp-pill">{server.tier}</span>}
                        {server.tools.length > 0 && <span>{server.tools.length} alat terdaftar</span>}
                      </div>
                    </div>
                    <div className="mcp-catalog-row__actions">
                      <button type="button" className="mcp-btn" onClick={() => void handleStart(server.name)} disabled={isMutating}>
                        Mulai
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </details>
    </section>
  );
}

function ToolList({
  server,
  onToggleTool,
}: {
  server: RegisteredMCPServer;
  onToggleTool: (server: RegisteredMCPServer, tool: MCPDiscoveredTool) => void;
}) {
  if (server.tools.length === 0) {
    return <div className="mcp-state">Muat alat untuk melihat apa saja yang disediakan server ini.</div>;
  }

  return (
    <div className="mcp-tool-list">
      {server.tools.map((tool) => (
        <div key={tool.name} className="mcp-tool-row">
          <label className="mcp-toggle">
            <input
              type="checkbox"
              checked={tool.enabled}
              onChange={() => onToggleTool(server, tool)}
              aria-label={`${tool.enabled ? "Nonaktifkan" : "Aktifkan"} ${tool.name}`}
            />
            <span>{tool.enabled ? "Aktif" : "Nonaktif"}</span>
          </label>
          <div>
            <strong>{tool.name}</strong>
            <p>{tool.description || "Tanpa deskripsi."}</p>
            {tool.loaded && (
              <code>{tool.registeredToolName ?? tool.registered_tool_name ?? tool.namespacedName}</code>
            )}
            <code>{parameterSummary(tool.inputSchema ?? tool.input_schema ?? {})}</code>
          </div>
        </div>
      ))}
    </div>
  );
}

function ServerCard({
  server,
  onOpen,
  onDiscover,
  onToggle,
  onRemove,
}: {
  server: RegisteredMCPServer;
  onOpen: (server: RegisteredMCPServer) => void;
  onDiscover: (server: RegisteredMCPServer) => void;
  onToggle: (server: RegisteredMCPServer) => void;
  onRemove: (server: RegisteredMCPServer) => void;
}) {
  return (
    <article className="mcp-card">
      <button type="button" className="mcp-card__main" onClick={() => onOpen(server)}>
        <div className="mcp-card__meta">
          <span className="mcp-pill">{providerLabel(server)}</span>
          <span className="mcp-pill">{server.transport}</span>
          <span className={`mcp-pill${statusClass(server)}`}>{server.enabled ? server.status : "disabled"}</span>
        </div>
        <div className="mcp-card__title-row">
          <div className="mcp-card__icon" aria-hidden="true">
            MCP
          </div>
          <div className="mcp-card__title">
            <h3>{server.name}</h3>
            <p>{server.enabledToolsCount} dari {server.toolsCount} alat aktif</p>
          </div>
        </div>
        <p className="mcp-card__description">
          {server.error || (server.toolsCount ? "Alat telah ditemukan dan siap digunakan di chat." : "Terdaftar. Muat alat saat Anda siap memulai penemuan.")}
        </p>
      </button>
      <div className="mcp-card__actions">
        <button type="button" className="mcp-btn" onClick={() => onToggle(server)}>
          {server.enabled ? "Nonaktifkan" : "Aktifkan"}
        </button>
        <button type="button" className="mcp-btn" onClick={() => onDiscover(server)} disabled={!server.enabled}>
          Muat Alat
        </button>
        <button type="button" className="mcp-btn" onClick={() => onOpen(server)}>
          Rincian
        </button>
        {!(server.isManaged ?? server.is_managed) && (
          <button type="button" className="mcp-btn" onClick={() => onRemove(server)}>
            Hapus
          </button>
        )}
      </div>
    </article>
  );
}

function DetailsDialog({
  server,
  onClose,
  onDiscover,
  onToggleServer,
  onToggleTool,
}: {
  server: RegisteredMCPServer;
  onClose: () => void;
  onDiscover: (server: RegisteredMCPServer) => void;
  onToggleServer: (server: RegisteredMCPServer) => void;
  onToggleTool: (server: RegisteredMCPServer, tool: MCPDiscoveredTool) => void;
}) {
  return (
    <Dialog title={server.name} onClose={onClose}>
      <div className="mcp-dialog__body">
        <div className="mcp-detail-grid">
          <span>Transport</span>
          <strong>{server.transport}</strong>
          <span>Penyedia</span>
          <strong>{providerLabel(server)}</strong>
          <span>Namespace</span>
          <strong>{server.serverNamespace ?? server.server_namespace ?? server.name}</strong>
          <span>Status</span>
          <strong>{server.enabled ? server.status : "disabled"}</strong>
          <span>Alat</span>
          <strong>{server.enabledToolsCount} aktif / {server.toolsCount} ditemukan</strong>
          <span>Penemuan terakhir</span>
          <strong>{server.lastDiscoveredAt || "Belum pernah"}</strong>
        </div>
        {server.error && (
          <div className="mcp-state mcp-state--error" role="alert">
            {server.error}
          </div>
        )}
        <div className="mcp-config-list">
          <h3>Konfigurasi Server</h3>
          <ConfigPreview config={server.config ?? server.displayConfig} />
        </div>
        {serverSecrets(server).length > 0 && (
          <div className="mcp-config-list">
            <h3>Env Terkelola</h3>
            <div className="mcp-tool-list">
              {serverSecrets(server).map((secret) => {
                const key = secret.secretKey ?? secret.secret_key ?? secret.envKey ?? secret.env_key ?? secret.key;
                return (
                  <div key={key} className="mcp-tool-row">
                    <span className={`mcp-pill${secret.missing ? " mcp-pill--error" : " mcp-pill--success"}`}>
                      {secret.status}
                    </span>
                    <div>
                      <strong>{key}</strong>
                      <p>{secret.source === "managed" ? "Dienkripsi dan disuntikkan saat runtime" : "Cadangan environment lokal"}</p>
                      <code>{secret.configured ? "***REDACTED***" : "belum diatur"}</code>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        <div className="mcp-config-list">
          <h3>Alat</h3>
          <ToolList server={server} onToggleTool={onToggleTool} />
        </div>
        <div className="mcp-dialog__actions">
          <button type="button" className="mcp-btn" onClick={onClose}>
            Tutup
          </button>
          <button type="button" className="mcp-btn" onClick={() => onToggleServer(server)}>
            {server.enabled ? "Nonaktifkan Server" : "Aktifkan Server"}
          </button>
          <button type="button" className="mcp-btn mcp-btn--primary" onClick={() => onDiscover(server)} disabled={!server.enabled}>
            Muat Alat
          </button>
        </div>
      </div>
    </Dialog>
  );
}

/** Inline MCP catalog (formerly a full-screen modal) — rendered as the body
 * of the "Server MCP" admin page. Import/details remain nested modals. */
export function McpCatalog() {
  const toast = useToast();
  const [data, setData] = useState<MCPRegistryPayload>({ servers: [] });
  const [filters, setFilters] = useState<RegistryFilters>(DEFAULT_FILTERS);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [details, setDetails] = useState<RegisteredMCPServer | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      setData(await listServers());
    } catch (error) {
      setError(readErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleServers = useMemo(() => filterServers(data.servers, filters), [data.servers, filters]);

  const replaceServer = (server: RegisteredMCPServer) => {
    setData((current) => ({
      servers: current.servers.map((item) => (item.id === server.id ? server : item)),
    }));
    setDetails((current) => (current?.id === server.id ? server : current));
  };

  const handleOpenServer = async (server: RegisteredMCPServer) => {
    try {
      setDetails(await getServer(server.id));
    } catch (error) {
      toast.show(`Gagal memuat rincian server: ${readErrorMessage(error)}`, "error");
    }
  };

  const handleDiscover = async (server: RegisteredMCPServer) => {
    try {
      const result = await discoverServer(server.id);
      replaceServer(result.server);
      toast.show(result.reload?.error ? `Registrasi runtime chat gagal: ${result.reload.error}` : "Alat MCP dimuat", result.reload?.error ? "error" : "success");
    } catch (error) {
      toast.show(`Penemuan alat gagal: ${readErrorMessage(error)}`, "error");
      await load();
    }
  };

  const handleToggleServer = async (server: RegisteredMCPServer) => {
    try {
      const result = await toggleServer(server.id, { enabled: !server.enabled });
      replaceServer(result.server);
      toast.show(result.server.enabled ? "Server MCP diaktifkan" : "Server MCP dinonaktifkan", "success");
    } catch (error) {
      toast.show(`Gagal memperbarui server: ${readErrorMessage(error)}`, "error");
    }
  };

  const handleToggleTool = async (server: RegisteredMCPServer, tool: MCPDiscoveredTool) => {
    try {
      const result = await toggleTool(server.id, tool.name, { enabled: !tool.enabled });
      replaceServer(result.server);
      toast.show(result.reload?.error ? `Registrasi runtime chat gagal: ${result.reload.error}` : "Alat MCP diperbarui", result.reload?.error ? "error" : "success");
    } catch (error) {
      toast.show(`Gagal memperbarui alat: ${readErrorMessage(error)}`, "error");
    }
  };

  const handleRemove = async (server: RegisteredMCPServer) => {
    try {
      await removeServer(server.id);
      setData((current) => ({ servers: current.servers.filter((item) => item.id !== server.id) }));
      setDetails((current) => (current?.id === server.id ? null : current));
      toast.show("Server MCP dihapus", "success");
    } catch (error) {
      toast.show(`Gagal menghapus server: ${readErrorMessage(error)}`, "error");
    }
  };

  return (
    <div className="mcp-catalog mcp-catalog--page">
      <ToolHiveSection onImported={(payload) => setData(payload)} />
      <section className="mcp-section">
        <div className="mcp-section__header">
          <div>
            <h3>Server Terdaftar</h3>
            <p>{data.servers.length} terkonfigurasi</p>
          </div>
          <div className="mcp-section__actions">
            <button type="button" className="mcp-btn" onClick={() => void load()} aria-label="Segarkan server MCP">
              Segarkan
            </button>
            <button type="button" className="mcp-btn mcp-btn--primary" onClick={() => setImportOpen(true)}>
              Tambah Server
            </button>
          </div>
        </div>
        <div className="mcp-toolbar">
          <label className="mcp-search">
            <span>Cari server MCP</span>
            <input
              value={filters.query}
              type="search"
              placeholder="Cari server dan alat"
              onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
            />
          </label>
          <select
            aria-label="Saring status server"
            value={filters.status}
            onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as StatusFilter }))}
          >
            <option value="all">Semua Status</option>
            <option value="enabled">Aktif</option>
            <option value="disabled">Nonaktif</option>
            <option value="failed">Gagal</option>
          </select>
          <select
            aria-label="Urutkan server"
            value={filters.sort}
            onChange={(event) => setFilters((current) => ({ ...current, sort: event.target.value as SortMode }))}
          >
            <option value="name">Nama</option>
            <option value="status">Status</option>
            <option value="tools">Alat</option>
          </select>
        </div>

        <div aria-live="polite">
          {isLoading && <div className="mcp-state">Memuat server MCP...</div>}
          {!isLoading && error && (
            <div className="mcp-state mcp-state--error" role="alert">
              {error}
            </div>
          )}
          {!isLoading && !error && data.servers.length === 0 && (
            <div className="mcp-state">Tambahkan workload ToolHive, URL ToolHive, atau konfigurasi JSON mcpServers standar.</div>
          )}
          {!isLoading && !error && data.servers.length > 0 && visibleServers.length === 0 && (
            <div className="mcp-state">Tidak ada server MCP yang cocok dengan filter.</div>
          )}
        </div>

        {visibleServers.length > 0 && (
          <div className="mcp-grid">
            {visibleServers.map((server) => (
              <ServerCard
                key={server.id}
                server={server}
                onOpen={(server) => void handleOpenServer(server)}
                onDiscover={(server) => void handleDiscover(server)}
                onToggle={(server) => void handleToggleServer(server)}
                onRemove={(server) => void handleRemove(server)}
              />
            ))}
          </div>
        )}
      </section>
      {importOpen && (
        <ImportDialog
          onClose={() => setImportOpen(false)}
          onImported={(payload) => {
            setData(payload);
            toast.show("Server MCP terdaftar", "success");
          }}
        />
      )}
      {details && (
        <DetailsDialog
          server={details}
          onClose={() => setDetails(null)}
          onDiscover={(server) => void handleDiscover(server)}
          onToggleServer={(server) => void handleToggleServer(server)}
          onToggleTool={(server, tool) => void handleToggleTool(server, tool)}
        />
      )}
    </div>
  );
}
