import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../Toast";
import { McpCatalogPanel } from "./McpCatalogPanel";
import type { MCPRegistryPayload, RegisteredMCPServer } from "./types";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const playwrightServer: RegisteredMCPServer = {
  id: "server-playwright",
  name: "playwright",
  title: "playwright",
  transport: "stdio",
  enabled: true,
  status: "enabled",
  error: null,
  registeredAt: "2026-05-20T00:00:00+00:00",
  updatedAt: "2026-05-20T00:00:00+00:00",
  lastDiscoveredAt: null,
  tools: [],
  toolsCount: 0,
  enabledToolsCount: 0,
  displayConfig: {
    transport: "stdio",
    command: "docker",
    args: ["run", "-i", "--rm", "mcp/playwright"],
    env: { PLAYWRIGHT_TOKEN: "***REDACTED***" },
  },
  secrets: [
    {
      key: "PLAYWRIGHT_TOKEN",
      secretKey: "PLAYWRIGHT_TOKEN",
      source: "managed",
      configured: true,
      missing: false,
      status: "configured",
      value: "***REDACTED***",
    },
  ],
};

const discoveredServer: RegisteredMCPServer = {
  ...playwrightServer,
  status: "running",
  lastDiscoveredAt: "2026-05-20T00:01:00+00:00",
  toolsCount: 2,
  enabledToolsCount: 2,
  tools: [
    {
      name: "browser_click",
      namespacedName: "playwright.browser_click",
      description: "Click an element",
      inputSchema: {
        type: "object",
        properties: { selector: { type: "string" } },
        required: ["selector"],
      },
      enabled: true,
      discoveredAt: "2026-05-20T00:01:00+00:00",
    },
    {
      name: "browser_snapshot",
      namespacedName: "playwright.browser_snapshot",
      description: "Capture page structure",
      inputSchema: { type: "object", properties: {}, required: [] },
      enabled: true,
      discoveredAt: "2026-05-20T00:01:00+00:00",
    },
  ],
};

const basePayload: MCPRegistryPayload = {
  servers: [playwrightServer],
};

const internalServer: RegisteredMCPServer = {
  id: "internal-openbench",
  name: "openbench",
  title: "openbench",
  source: "internal",
  providerKind: "internal",
  sourceType: "internal",
  serverNamespace: "openbench",
  isManaged: true,
  transport: "in-memory",
  enabled: true,
  status: "registered",
  error: null,
  registeredAt: "2026-05-20T00:00:00+00:00",
  updatedAt: "2026-05-20T00:00:00+00:00",
  lastDiscoveredAt: "2026-05-20T00:01:00+00:00",
  tools: [
    {
      name: "filter_records",
      namespacedName: "openbench.filter_records",
      description: "Filter rows",
      inputSchema: { type: "object", properties: {}, required: [] },
      enabled: true,
      discoveredAt: "2026-05-20T00:01:00+00:00",
      loaded: true,
      registeredToolName: "openbench_filter_records",
    },
  ],
  toolsCount: 1,
  enabledToolsCount: 1,
  displayConfig: {
    transport: "in-memory",
    namespace: "openbench",
  },
};

const toolHiveStatus = {
  available: true,
  apiAvailable: true,
  cliAvailable: false,
  version: "v0.test",
  apiBaseUrl: "http://127.0.0.1:8080",
  source: "api",
  error: null,
  setupHint: null,
  uiCliDetected: false,
  cliPath: "thv",
  managementMode: "api",
};

const toolHiveWorkload = {
  name: "toolhive-doc-mcp",
  status: "running",
  url: "http://127.0.0.1:19767/mcp",
  package: "ghcr.io/stackloklabs/toolhive-doc-mcp:test",
  port: 19767,
  group: "default",
  created: "2026-05-20T00:00:00+00:00",
  transport: "streamable-http",
};

const toolHiveRegistryServer = {
  name: "toolhive-doc-mcp",
  title: "ToolHive Docs",
  description: "Search ToolHive docs",
  transport: "streamable-http",
  tier: "Official",
  type: "container",
  url: null,
  tools: ["query_docs"],
};

function toolHiveResponse(url: string): Response | null {
  if (url === "/toolhive/status") return jsonResponse(toolHiveStatus);
  if (url === "/toolhive/workloads") return jsonResponse({ workloads: [toolHiveWorkload] });
  if (url === "/toolhive/registry/servers") return jsonResponse({ servers: [toolHiveRegistryServer] });
  return null;
}

function renderPanel() {
  return render(
    <ToastProvider durationMs={0}>
      <McpCatalogPanel open={true} onClose={() => undefined} />
    </ToastProvider>,
  );
}

describe("McpCatalogPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders registered servers and filters by search text", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return toolHiveResponse(url) ?? jsonResponse(basePayload);
    }));

    renderPanel();

    expect(await screen.findByText("playwright")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search MCP servers"), "stdio");
    expect(screen.getByText("playwright")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Search MCP servers"));
    await userEvent.type(screen.getByLabelText("Search MCP servers"), "filesystem");
    expect(screen.getByText("No MCP servers match the current filters.")).toBeInTheDocument();
  });

  it("renders internal managed MCP tools in the catalog", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/mcp/catalogs/servers/internal-openbench") return jsonResponse(internalServer);
      return toolHiveResponse(url) ?? jsonResponse({ servers: [internalServer] });
    }));

    renderPanel();

    expect(await screen.findByText("openbench")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search MCP servers"), "internal");
    expect(screen.getByText("openbench")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /openbench/ }));
    expect(screen.getByText("openbench_filter_records")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog", { name: "openbench" })).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("imports pasted mcpServers JSON and shows validation errors", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const toolHive = toolHiveResponse(url);
      if (toolHive) return toolHive;
      if (url === "/mcp/catalogs" && !init) return jsonResponse({ servers: [] });
      if (url === "/mcp/catalogs/import") {
        const body = JSON.parse(String(init?.body));
        if (String(body.config).includes("bad")) {
          return jsonResponse({ detail: "MCP config must contain a top-level mcpServers object." }, 400);
        }
        if (String(body.config).includes("PLAYWRIGHT_TOKEN")) {
          expect(body.secrets).toEqual({ PLAYWRIGHT_TOKEN: "typed-token" });
          expect(JSON.stringify(body.secrets)).not.toContain("pasted-token");
          expect(JSON.stringify(body.secrets)).not.toContain("removed-token");
        }
        return jsonResponse(basePayload);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    await screen.findByText("Add a ToolHive workload, ToolHive URL, or standard mcpServers JSON config.");
    await userEvent.click(screen.getByRole("button", { name: "Add servers" }));
    const dialog = screen.getByRole("dialog", { name: "Add MCP servers" });
    expect((screen.getByLabelText("MCP JSON config") as HTMLTextAreaElement).value).not.toContain("HF_TOKEN");
    expect(within(dialog).getByText("Docker env")).toBeInTheDocument();
    expect(within(dialog).getByText(/encrypted before saving/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("MCP JSON config"), { target: { value: '{"bad":{}}' } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Register servers" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("mcpServers");
    fireEvent.change(screen.getByLabelText("MCP JSON config"), {
      target: {
        value:
          '{"mcpServers":{"playwright":{"command":"docker","env":{"PLAYWRIGHT_TOKEN":"pasted-token"}}}}',
      },
    });
    await userEvent.type(within(dialog).getByLabelText("Key"), "REMOVED_TOKEN");
    await userEvent.type(within(dialog).getByLabelText("Value"), "removed-token");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add env" }));
    const keyInputs = within(dialog).getAllByLabelText("Key");
    const valueInputs = within(dialog).getAllByLabelText("Value");
    await userEvent.type(keyInputs[1], "PLAYWRIGHT_TOKEN");
    await userEvent.type(valueInputs[1], "typed-token");
    await userEvent.click(within(dialog).getAllByRole("button", { name: "Remove" })[0]);
    await userEvent.click(within(dialog).getByRole("button", { name: "Register servers" }));

    expect(await screen.findByText("playwright")).toBeInTheDocument();
  });

  it("loads discovered tools and renders parameter summaries", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const toolHive = toolHiveResponse(url);
      if (toolHive) return toolHive;
      if (url === "/mcp/catalogs") return jsonResponse(basePayload);
      if (url === "/mcp/catalogs/servers/server-playwright" && !init) return jsonResponse(discoveredServer);
      if (url === "/mcp/catalogs/servers/server-playwright/discover") {
        return jsonResponse({ server: discoveredServer, reload: {} });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Load tools" }));
    expect(await screen.findByText("2 of 2 tools enabled")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(await screen.findByText("browser_click")).toBeInTheDocument();
    expect(screen.getByText("selector: string required")).toBeInTheDocument();
    expect(screen.getByText("Encrypted and injected at runtime")).toBeInTheDocument();
    expect(screen.getByText("***REDACTED***")).toBeInTheDocument();
  });

  it("toggles servers and individual tools", async () => {
    const disabledServer = { ...playwrightServer, enabled: false, status: "disabled" };
    const toolDisabledServer = {
      ...discoveredServer,
      enabledToolsCount: 1,
      tools: discoveredServer.tools.map((tool) =>
        tool.name === "browser_click" ? { ...tool, enabled: false } : tool,
      ),
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const toolHive = toolHiveResponse(url);
      if (toolHive) return toolHive;
      if (url === "/mcp/catalogs") return jsonResponse({ servers: [discoveredServer] });
      if (url === "/mcp/catalogs/servers/server-playwright" && !init) return jsonResponse(discoveredServer);
      if (url === "/mcp/catalogs/servers/server-playwright/enable") {
        expect(JSON.parse(String(init?.body))).toEqual({ enabled: false });
        return jsonResponse({ server: disabledServer, reload: {} });
      }
      if (url === "/mcp/catalogs/servers/server-playwright/tools/browser_click/enable") {
        expect(JSON.parse(String(init?.body))).toEqual({ enabled: false });
        return jsonResponse({ server: toolDisabledServer, reload: {} });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: /playwright/ }));
    await userEvent.click(within(screen.getByRole("dialog", { name: "playwright" })).getByLabelText("Disable browser_click"));
    expect(await screen.findByText("1 enabled / 2 discovered")).toBeInTheDocument();

    await userEvent.click(within(screen.getByRole("dialog", { name: "playwright" })).getByRole("button", { name: "Disable server" }));
    await waitFor(() => expect(screen.getAllByText("disabled").length).toBeGreaterThan(0));
  });

  it("does not render obsolete URL or OCI import fields", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return toolHiveResponse(url) ?? jsonResponse({ servers: [] });
    }));

    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Add servers" }));

    expect(screen.queryByText("Catalog URL")).not.toBeInTheDocument();
    expect(screen.queryByText("OCI Reference")).not.toBeInTheDocument();
  });

  it("shows ToolHive setup copy when ToolHive is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/toolhive/status") {
        return jsonResponse({
          ...toolHiveStatus,
          available: false,
          setupHint: "Install ToolHive with winget install stacklok.thv",
        });
      }
      if (url === "/mcp/catalogs") return jsonResponse({ servers: [] });
      throw new Error(`Unexpected request: ${url}`);
    }));

    renderPanel();

    expect(await screen.findByText("Install ToolHive with winget install stacklok.thv")).toBeInTheDocument();
  });

  it("shows the ToolHive UI companion workflow and keeps advanced controls collapsed", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return toolHiveResponse(url) ?? jsonResponse({ servers: [] });
    }));

    renderPanel();

    expect(await screen.findByText("Manage servers in ToolHive UI")).toBeInTheDocument();
    expect(await screen.findByText((_content, element) => element?.textContent === "Detected CLI: thv")).toBeInTheDocument();
    const advanced = screen.getByText("Advanced local controls").closest("details");
    expect(advanced).not.toBeNull();
    expect(advanced).not.toHaveAttribute("open");
  });

  it("imports a running ToolHive workload into registered servers", async () => {
    const importedPayload: MCPRegistryPayload = {
      servers: [
        {
          ...playwrightServer,
          id: "server-toolhive-doc-mcp",
          name: "toolhive-doc-mcp",
          title: "toolhive-doc-mcp",
          source: "toolhive",
          transport: "streamable-http",
          displayConfig: { transport: "streamable-http", url: "http://127.0.0.1:19767/mcp" },
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const toolHive = toolHiveResponse(url);
      if (toolHive) return toolHive;
      if (url === "/mcp/catalogs") return jsonResponse({ servers: [] });
      if (url === "/mcp/catalogs/toolhive/import-running") {
        expect(JSON.parse(String(init?.body))).toEqual({ names: ["toolhive-doc-mcp"] });
        return jsonResponse(importedPayload);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    await screen.findAllByText("toolhive-doc-mcp");
    await userEvent.click(screen.getByRole("button", { name: "Import into OpenBench" }));
    await waitFor(() => expect(screen.getAllByText("toolhive-doc-mcp").length).toBeGreaterThan(1));
  });

  it("starts a ToolHive registry server from search results", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const toolHive = toolHiveResponse(url);
      if (toolHive) return toolHive;
      if (url === "/mcp/catalogs") return jsonResponse({ servers: [] });
      if (url === "/toolhive/workloads" && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({
          target: "toolhive-doc-mcp",
        });
        return jsonResponse({ workload: toolHiveWorkload });
      }
      if (url === "/mcp/catalogs/toolhive/import-running") {
        return jsonResponse({ servers: [] });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    await userEvent.click(await screen.findByText("Advanced local controls"));
    expect(await screen.findByText("ToolHive Docs")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/toolhive/workloads", expect.objectContaining({ method: "POST" })));
  });

  it("registers a ToolHive URL copied from the ToolHive UI", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const toolHive = toolHiveResponse(url);
      if (toolHive) return toolHive;
      if (url === "/mcp/catalogs") return jsonResponse({ servers: [] });
      if (url === "/mcp/catalogs/import") {
        const body = JSON.parse(String(init?.body));
        expect(JSON.parse(String(body.config))).toEqual({
          mcpServers: {
            awsdocs: {
              url: "http://127.0.0.1:19767/mcp",
            },
          },
        });
        return jsonResponse(basePayload);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    await screen.findByText("Manage servers in ToolHive UI");
    await userEvent.clear(screen.getByLabelText("Server name"));
    await userEvent.type(screen.getByLabelText("Server name"), "awsdocs");
    await userEvent.type(screen.getByLabelText("Copied ToolHive MCP URL"), "http://127.0.0.1:19767/mcp");
    await userEvent.click(screen.getByRole("button", { name: "Register copied URL" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/mcp/catalogs/import",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
