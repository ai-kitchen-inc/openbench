import { render, screen } from "@testing-library/react";
import { ToastProvider } from "../../Toast";
import { McpServersPage } from "./McpServersPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/mcp/catalogs") return jsonResponse({ servers: [] });
      if (url.startsWith("/toolhive/")) return jsonResponse({ detail: "off" }, 404);
      throw new Error(`Unexpected fetch: ${url}`);
    }),
  );
}

describe("McpServersPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("opens the import dialog when deep-linked with initialImportOpen", async () => {
    stubFetch();
    render(
      <ToastProvider durationMs={0}>
        <McpServersPage initialImportOpen />
      </ToastProvider>,
    );
    expect(await screen.findByRole("dialog", { name: "Add MCP servers" })).toBeInTheDocument();
  });

  it("keeps the import dialog closed by default", async () => {
    stubFetch();
    render(
      <ToastProvider durationMs={0}>
        <McpServersPage />
      </ToastProvider>,
    );
    expect(await screen.findByRole("dialog", { name: "MCP Servers" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Add MCP servers" })).toBeNull();
  });
});
