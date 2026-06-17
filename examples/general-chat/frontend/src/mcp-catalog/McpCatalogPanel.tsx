import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
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
  if (!status) return "unchecked";
  if (status.managementMode === "api") return "API";
  if (status.managementMode === "ui-cli") return "ToolHive UI CLI";
  if (status.managementMode === "cli") return "CLI";
  return "unavailable";
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
          <button type="button" className="mcp-icon-btn" onClick={onClose} aria-label="Close dialog">
            <span aria-hidden="true">x</span>
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
    <Dialog title="Add MCP servers" onClose={onClose} initialFocusRef={inputRef}>
      <form className="mcp-dialog__body" onSubmit={(event) => void handleSubmit(event)}>
        <label className="mcp-field">
          <span>MCP JSON config</span>
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
          Validation checks the JSON shape only. OpenBench starts command-based MCP servers only when you load tools or use chat.
        </div>
        <div className="mcp-config-list">
          <h3>Docker env</h3>
          <div className="mcp-warning">
            Docker env values entered here or pasted in JSON <code>env</code> are encrypted before saving and only injected at runtime. Use <code>{'${ENV_VAR}'}</code> to read from your local environment instead.
          </div>
          <div className="mcp-config-list">
            {secretRows.map((row) => (
              <div key={row.id} className="mcp-detail-grid mcp-detail-grid--forms">
                <label className="mcp-field">
                  <span>Key</span>
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
                  <span>Value</span>
                  <input
                    type="password"
                    value={row.value}
                    autoComplete="off"
                    placeholder="Docker env value"
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
                  Remove
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
            Add env
          </button>
        </div>
        {error && (
          <div className="mcp-state mcp-state--error" role="alert">
            {error}
          </div>
        )}
        <div className="mcp-dialog__actions">
          <button type="button" className="mcp-btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="mcp-btn mcp-btn--primary" disabled={!config.trim() || isSubmitting}>
            {isSubmitting ? "Registering..." : "Register servers"}
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
    return "No parameters";
  }
  const required = Array.isArray(schema.required) ? schema.required : [];
  const parts = Object.entries(properties as Record<string, Record<string, unknown>>).map(([name, value]) => {
    const type = typeof value?.type === "string" ? value.type : "value";
    return `${name}: ${type}${required.includes(name) ? " required" : ""}`;
  });
  return parts.length ? parts.join(", ") : "No parameters";
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
      toast.show("ToolHive server imported", "success");
    } catch (error) {
      toast.show(`Could not add ToolHive server: ${readErrorMessage(error)}`, "error");
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
      toast.show("ToolHive workload started", "success");
    } catch (error) {
      toast.show(`Could not start ToolHive workload: ${readErrorMessage(error)}`, "error");
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
      toast.show("ToolHive URL registered", "success");
    } catch (error) {
      toast.show(`Could not register ToolHive URL: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  };

  const handleWorkloadAction = async (action: "stop" | "restart" | "delete", name: string) => {
    if (action === "delete" && !window.confirm(`Delete ToolHive workload ${name}? This stops and removes the ToolHive workload, not just the OpenBench reference.`)) {
      return;
    }
    setIsMutating(true);
    try {
      if (action === "stop") await stopToolHiveWorkload(name);
      if (action === "restart") await restartToolHiveWorkload(name);
      if (action === "delete") await deleteToolHiveWorkload(name);
      await load();
      toast.show(`ToolHive workload ${action} request sent`, "success");
    } catch (error) {
      toast.show(`ToolHive ${action} failed: ${readErrorMessage(error)}`, "error");
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
              : "Use ToolHive UI servers in OpenBench"}
          </p>
        </div>
        <button type="button" className="mcp-btn" onClick={() => void load()} disabled={isLoading}>
          Refresh running servers
        </button>
      </div>

      {isLoading && <div className="mcp-state">Checking ToolHive...</div>}
      {!isLoading && error && (
        <div className="mcp-state mcp-state--error" role="alert">
          {error}
        </div>
      )}
      {!isLoading && status && !status.available && (
        <div className="mcp-warning">
          {status.setupHint || "Install ToolHive, verify with thv version, then start the local API with thv serve."}
        </div>
      )}
      {!isLoading && status?.available && !status.apiAvailable && (
        <div className="mcp-warning">
          ToolHive API is not running. OpenBench can still import running servers through the
          {status.uiCliDetected ? " ToolHive UI bundled CLI" : " ToolHive CLI"}, but registry browsing and local controls need <code>thv serve</code>.
        </div>
      )}

      <div className="mcp-warning mcp-toolhive-companion">
        <strong>Manage servers in ToolHive UI</strong>
        <p>
          Start, configure, and inspect MCP servers in the ToolHive desktop app. Then refresh here
          and import the running server into OpenBench for tool discovery and chat use.
        </p>
        <div className="mcp-links">
          <a href="https://docs.stacklok.com/toolhive/guides-ui/" target="_blank" rel="noreferrer">
            ToolHive UI guide
          </a>
          <a href="https://docs.stacklok.com/toolhive/guides-ui/client-configuration" target="_blank" rel="noreferrer">
            Copy MCP server URL
          </a>
        </div>
        {status?.cliPath && <code className="mcp-inline-code">Detected CLI: {status.cliPath}</code>}
      </div>

      <div className="mcp-config-list">
        <h3>Running ToolHive servers</h3>
        {workloads.length === 0 ? (
          <div className="mcp-state">No running ToolHive MCP servers found. Start one in ToolHive UI, then refresh.</div>
        ) : (
          <div className="mcp-catalog-list">
            {workloads.map((workload) => (
              <div key={workload.name} className="mcp-catalog-row">
                <div>
                  <strong>{workload.name}</strong>
                  <span>{workload.url || "No proxy URL discovered"}</span>
                  <div className="mcp-source-line">
                    <span className="mcp-pill">{workload.transport || "unknown"}</span>
                    <span className="mcp-pill">{workload.status}</span>
                  </div>
                </div>
                <div className="mcp-catalog-row__actions">
                  <button type="button" className="mcp-btn" onClick={() => void handleImportWorkload(workload.name)} disabled={isMutating || !workload.url}>
                    Import into OpenBench
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mcp-detail-grid mcp-detail-grid--forms">
        <label className="mcp-field">
          <span>Copied ToolHive MCP URL</span>
          <input value={directUrl} onChange={(event) => setDirectUrl(event.target.value)} placeholder="http://127.0.0.1:19767/mcp" />
        </label>
        <label className="mcp-field">
          <span>Server name</span>
          <input value={directName} onChange={(event) => setDirectName(event.target.value)} />
        </label>
        <button type="button" className="mcp-btn" onClick={() => void handleRegisterUrl()} disabled={isMutating || !directUrl.trim()}>
          Register copied URL
        </button>
      </div>

      <details className="mcp-advanced-controls">
        <summary>Advanced local controls</summary>
        <div className="mcp-advanced-controls__body">
          <div className="mcp-detail-grid mcp-detail-grid--forms">
            <label className="mcp-field">
              <span>Registry server</span>
              <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="toolhive-doc-mcp" />
            </label>
            <label className="mcp-field">
              <span>Workload name</span>
              <input value={workloadName} onChange={(event) => setWorkloadName(event.target.value)} placeholder="Optional" />
            </label>
            <button type="button" className="mcp-btn mcp-btn--primary" onClick={() => void handleStart(target, workloadName)} disabled={isMutating || !target.trim()}>
              Start registry server
            </button>
          </div>

          <div className="mcp-detail-grid mcp-detail-grid--forms">
            <label className="mcp-field">
              <span>Remote MCP URL for ToolHive to proxy</span>
              <input value={remoteUrl} onChange={(event) => setRemoteUrl(event.target.value)} placeholder="https://example.com/mcp" />
            </label>
            <label className="mcp-toggle mcp-toggle--field">
              <input type="checkbox" checked={allowRemote} onChange={() => setAllowRemote((current) => !current)} />
              <span>User approved remote URL</span>
            </label>
            <button type="button" className="mcp-btn" onClick={() => void handleStart(remoteUrl, workloadName, allowRemote)} disabled={isMutating || !remoteUrl.trim()}>
              Start remote proxy
            </button>
          </div>

          {workloads.length > 0 && (
            <div className="mcp-config-list">
              <h3>Workload controls</h3>
              <div className="mcp-catalog-list">
                {workloads.map((workload) => (
                  <div key={workload.name} className="mcp-catalog-row">
                    <div>
                      <strong>{workload.name}</strong>
                      <span>{workload.url || "No proxy URL discovered"}</span>
                    </div>
                    <div className="mcp-catalog-row__actions">
                      <button type="button" className="mcp-btn" onClick={() => void handleWorkloadAction("restart", workload.name)} disabled={isMutating}>
                        Restart
                      </button>
                      <button type="button" className="mcp-btn" onClick={() => void handleWorkloadAction("stop", workload.name)} disabled={isMutating}>
                        Stop
                      </button>
                      <button type="button" className="mcp-btn" onClick={() => void handleWorkloadAction("delete", workload.name)} disabled={isMutating}>
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mcp-config-list">
            <h3>ToolHive registry</h3>
            <label className="mcp-search">
              <span>Search ToolHive registry</span>
              <input value={query} type="search" placeholder="Search registry servers" onChange={(event) => setQuery(event.target.value)} />
            </label>
            {visibleRegistry.length === 0 ? (
              <div className="mcp-state">No registry servers loaded. Start thv serve to browse the ToolHive registry.</div>
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
                        {server.tools.length > 0 && <span>{server.tools.length} tools listed</span>}
                      </div>
                    </div>
                    <div className="mcp-catalog-row__actions">
                      <button type="button" className="mcp-btn" onClick={() => void handleStart(server.name)} disabled={isMutating}>
                        Start
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
    return <div className="mcp-state">Load tools to discover what this server exposes.</div>;
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
              aria-label={`${tool.enabled ? "Disable" : "Enable"} ${tool.name}`}
            />
            <span>{tool.enabled ? "Enabled" : "Disabled"}</span>
          </label>
          <div>
            <strong>{tool.name}</strong>
            <p>{tool.description || "No description provided."}</p>
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
            <p>{server.enabledToolsCount} of {server.toolsCount} tools enabled</p>
          </div>
        </div>
        <p className="mcp-card__description">
          {server.error || (server.toolsCount ? "Tools discovered and ready for chat." : "Registered. Load tools when you are ready to start discovery.")}
        </p>
      </button>
      <div className="mcp-card__actions">
        <button type="button" className="mcp-btn" onClick={() => onToggle(server)}>
          {server.enabled ? "Disable" : "Enable"}
        </button>
        <button type="button" className="mcp-btn" onClick={() => onDiscover(server)} disabled={!server.enabled}>
          Load tools
        </button>
        <button type="button" className="mcp-btn" onClick={() => onOpen(server)}>
          Details
        </button>
        {!(server.isManaged ?? server.is_managed) && (
          <button type="button" className="mcp-btn" onClick={() => onRemove(server)}>
            Remove
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
          <span>Provider</span>
          <strong>{providerLabel(server)}</strong>
          <span>Namespace</span>
          <strong>{server.serverNamespace ?? server.server_namespace ?? server.name}</strong>
          <span>Status</span>
          <strong>{server.enabled ? server.status : "disabled"}</strong>
          <span>Tools</span>
          <strong>{server.enabledToolsCount} enabled / {server.toolsCount} discovered</strong>
          <span>Last discovery</span>
          <strong>{server.lastDiscoveredAt || "Never"}</strong>
        </div>
        {server.error && (
          <div className="mcp-state mcp-state--error" role="alert">
            {server.error}
          </div>
        )}
        <div className="mcp-config-list">
          <h3>Server configuration</h3>
          <ConfigPreview config={server.config ?? server.displayConfig} />
        </div>
        {serverSecrets(server).length > 0 && (
          <div className="mcp-config-list">
            <h3>Managed env</h3>
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
                      <p>{secret.source === "managed" ? "Encrypted and injected at runtime" : "Local environment fallback"}</p>
                      <code>{secret.configured ? "***REDACTED***" : "missing"}</code>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        <div className="mcp-config-list">
          <h3>Tools</h3>
          <ToolList server={server} onToggleTool={onToggleTool} />
        </div>
        <div className="mcp-dialog__actions">
          <button type="button" className="mcp-btn" onClick={onClose}>
            Close
          </button>
          <button type="button" className="mcp-btn" onClick={() => onToggleServer(server)}>
            {server.enabled ? "Disable server" : "Enable server"}
          </button>
          <button type="button" className="mcp-btn mcp-btn--primary" onClick={() => onDiscover(server)} disabled={!server.enabled}>
            Load tools
          </button>
        </div>
      </div>
    </Dialog>
  );
}

export function McpCatalogPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
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
    if (open) void load();
  }, [load, open]);

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
      toast.show(`Could not load server details: ${readErrorMessage(error)}`, "error");
    }
  };

  const handleDiscover = async (server: RegisteredMCPServer) => {
    try {
      const result = await discoverServer(server.id);
      replaceServer(result.server);
      toast.show(result.reload?.error ? `Chat runtime registration failed: ${result.reload.error}` : "MCP tools loaded", result.reload?.error ? "error" : "success");
    } catch (error) {
      toast.show(`Tool discovery failed: ${readErrorMessage(error)}`, "error");
      await load();
    }
  };

  const handleToggleServer = async (server: RegisteredMCPServer) => {
    try {
      const result = await toggleServer(server.id, { enabled: !server.enabled });
      replaceServer(result.server);
      toast.show(result.server.enabled ? "MCP server enabled" : "MCP server disabled", "success");
    } catch (error) {
      toast.show(`Could not update server: ${readErrorMessage(error)}`, "error");
    }
  };

  const handleToggleTool = async (server: RegisteredMCPServer, tool: MCPDiscoveredTool) => {
    try {
      const result = await toggleTool(server.id, tool.name, { enabled: !tool.enabled });
      replaceServer(result.server);
      toast.show(result.reload?.error ? `Chat runtime registration failed: ${result.reload.error}` : "MCP tool updated", result.reload?.error ? "error" : "success");
    } catch (error) {
      toast.show(`Could not update tool: ${readErrorMessage(error)}`, "error");
    }
  };

  const handleRemove = async (server: RegisteredMCPServer) => {
    try {
      await removeServer(server.id);
      setData((current) => ({ servers: current.servers.filter((item) => item.id !== server.id) }));
      setDetails((current) => (current?.id === server.id ? null : current));
      toast.show("MCP server removed", "success");
    } catch (error) {
      toast.show(`Could not remove server: ${readErrorMessage(error)}`, "error");
    }
  };

  if (!open) return null;

  return (
    <Dialog title="MCP Servers" onClose={onClose}>
      <div className="mcp-catalog">
        <ToolHiveSection onImported={(payload) => setData(payload)} />
        <section className="mcp-section">
          <div className="mcp-section__header">
            <div>
              <h3>Registered servers</h3>
              <p>{data.servers.length} configured</p>
            </div>
            <div className="mcp-section__actions">
              <button type="button" className="mcp-btn" onClick={() => void load()} aria-label="Refresh MCP servers">
                Refresh
              </button>
              <button type="button" className="mcp-btn mcp-btn--primary" onClick={() => setImportOpen(true)}>
                Add servers
              </button>
            </div>
          </div>
          <div className="mcp-toolbar">
            <label className="mcp-search">
              <span>Search MCP servers</span>
              <input
                value={filters.query}
                type="search"
                placeholder="Search servers and tools"
                onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
              />
            </label>
            <select
              aria-label="Filter by server status"
              value={filters.status}
              onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as StatusFilter }))}
            >
              <option value="all">All status</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
              <option value="failed">Failed</option>
            </select>
            <select
              aria-label="Sort servers"
              value={filters.sort}
              onChange={(event) => setFilters((current) => ({ ...current, sort: event.target.value as SortMode }))}
            >
              <option value="name">Name</option>
              <option value="status">Status</option>
              <option value="tools">Tools</option>
            </select>
          </div>

          <div aria-live="polite">
            {isLoading && <div className="mcp-state">Loading MCP servers...</div>}
            {!isLoading && error && (
              <div className="mcp-state mcp-state--error" role="alert">
                {error}
              </div>
            )}
            {!isLoading && !error && data.servers.length === 0 && (
              <div className="mcp-state">Add a ToolHive workload, ToolHive URL, or standard mcpServers JSON config.</div>
            )}
            {!isLoading && !error && data.servers.length > 0 && visibleServers.length === 0 && (
              <div className="mcp-state">No MCP servers match the current filters.</div>
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
      </div>
      {importOpen && (
        <ImportDialog
          onClose={() => setImportOpen(false)}
          onImported={(payload) => {
            setData(payload);
            toast.show("MCP servers registered", "success");
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
    </Dialog>
  );
}
