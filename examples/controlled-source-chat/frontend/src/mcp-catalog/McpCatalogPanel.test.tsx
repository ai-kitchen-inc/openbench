import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../Toast";
import { McpCatalog } from "./McpCatalogPanel";
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
      <McpCatalog />
    </ToastProvider>,
  );
}

describe("McpCatalog", () => {
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
    await userEvent.type(screen.getByLabelText("Cari server MCP"), "stdio");
    expect(screen.getByText("playwright")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Cari server MCP"));
    await userEvent.type(screen.getByLabelText("Cari server MCP"), "filesystem");
    expect(screen.getByText("Tidak ada server MCP yang cocok dengan filter.")).toBeInTheDocument();
  });

  it("renders internal managed MCP tools in the catalog", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/mcp/catalogs/servers/internal-openbench") return jsonResponse(internalServer);
      return toolHiveResponse(url) ?? jsonResponse({ servers: [internalServer] });
    }));

    renderPanel();

    expect(await screen.findByText("openbench")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Cari server MCP"), "internal");
    expect(screen.getByText("openbench")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /openbench/ }));
    expect(screen.getByText("openbench_filter_records")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog", { name: "openbench" })).queryByRole("button", { name: "Hapus" })).not.toBeInTheDocument();
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

    await screen.findByText("Tambahkan workload ToolHive, URL ToolHive, atau konfigurasi JSON mcpServers standar.");
    await userEvent.click(screen.getByRole("button", { name: "Tambah Server" }));
    const dialog = screen.getByRole("dialog", { name: "Tambah Server MCP" });
    expect((screen.getByLabelText("Konfigurasi JSON MCP") as HTMLTextAreaElement).value).not.toContain("HF_TOKEN");
    expect(within(dialog).getByText("Env Docker")).toBeInTheDocument();
    expect(within(dialog).getByText(/dienkripsi sebelum disimpan/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Konfigurasi JSON MCP"), { target: { value: '{"bad":{}}' } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Daftarkan Server" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("mcpServers");
    fireEvent.change(screen.getByLabelText("Konfigurasi JSON MCP"), {
      target: {
        value:
          '{"mcpServers":{"playwright":{"command":"docker","env":{"PLAYWRIGHT_TOKEN":"pasted-token"}}}}',
      },
    });
    await userEvent.type(within(dialog).getByLabelText("Kunci"), "REMOVED_TOKEN");
    await userEvent.type(within(dialog).getByLabelText("Nilai"), "removed-token");
    await userEvent.click(within(dialog).getByRole("button", { name: "Tambah Env" }));
    const keyInputs = within(dialog).getAllByLabelText("Kunci");
    const valueInputs = within(dialog).getAllByLabelText("Nilai");
    await userEvent.type(keyInputs[1], "PLAYWRIGHT_TOKEN");
    await userEvent.type(valueInputs[1], "typed-token");
    await userEvent.click(within(dialog).getAllByRole("button", { name: "Hapus" })[0]);
    await userEvent.click(within(dialog).getByRole("button", { name: "Daftarkan Server" }));

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

    await userEvent.click(await screen.findByRole("button", { name: "Muat Alat" }));
    expect(await screen.findByText("2 dari 2 alat aktif")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Rincian" }));
    expect(await screen.findByText("browser_click")).toBeInTheDocument();
    expect(screen.getByText("selector: string wajib")).toBeInTheDocument();
    expect(screen.getByText("Dienkripsi dan disuntikkan saat runtime")).toBeInTheDocument();
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
    await userEvent.click(within(screen.getByRole("dialog", { name: "playwright" })).getByLabelText("Nonaktifkan browser_click"));
    expect(await screen.findByText("1 aktif / 2 ditemukan")).toBeInTheDocument();

    await userEvent.click(within(screen.getByRole("dialog", { name: "playwright" })).getByRole("button", { name: "Nonaktifkan Server" }));
    await waitFor(() => expect(screen.getAllByText("disabled").length).toBeGreaterThan(0));
  });

  it("does not render obsolete URL or OCI import fields", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return toolHiveResponse(url) ?? jsonResponse({ servers: [] });
    }));

    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Tambah Server" }));

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

    expect(await screen.findByText("Kelola server di ToolHive UI")).toBeInTheDocument();
    expect(await screen.findByText((_content, element) => element?.textContent === "CLI terdeteksi: thv")).toBeInTheDocument();
    const advanced = screen.getByText("Kontrol lokal lanjutan").closest("details");
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
    await userEvent.click(screen.getByRole("button", { name: "Impor ke OpenBench" }));
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

    await userEvent.click(await screen.findByText("Kontrol lokal lanjutan"));
    expect(await screen.findByText("ToolHive Docs")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mulai" }));
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

    await screen.findByText("Kelola server di ToolHive UI");
    await userEvent.clear(screen.getByLabelText("Nama server"));
    await userEvent.type(screen.getByLabelText("Nama server"), "awsdocs");
    await userEvent.type(screen.getByLabelText("URL MCP ToolHive yang disalin"), "http://127.0.0.1:19767/mcp");
    await userEvent.click(screen.getByRole("button", { name: "Daftarkan URL Tersalin" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/mcp/catalogs/import",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
