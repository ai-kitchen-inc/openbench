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
  getServer,
  importMCPConfig,
  listServers,
  removeServer,
  toggleServer,
  toggleTool,
} from "./api";
import { filterServers, type RegistryFilters, type SortMode, type StatusFilter } from "./filtering";
import type { MCPDiscoveredTool, MCPRegistryPayload, RegisteredMCPServer } from "./types";

const EXAMPLE_CONFIG = `{
  "mcpServers": {
    "playwright": {
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

function readErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
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

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError("");
    try {
      const payload = await importMCPConfig({ config });
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
  if (server.status === "running" || server.status === "enabled") return " mcp-pill--success";
  return "";
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
        <button type="button" className="mcp-btn" onClick={() => onRemove(server)}>
          Remove
        </button>
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
      toast.show(result.reload?.error ? `Tools loaded, but chat reload reported: ${result.reload.error}` : "MCP tools loaded", result.reload?.error ? "error" : "success");
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
      toast.show(result.reload?.error ? `Tool saved, but chat reload reported: ${result.reload.error}` : "MCP tool updated", result.reload?.error ? "error" : "success");
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
              <div className="mcp-state">Add a standard mcpServers JSON config to register command-based MCP servers.</div>
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
