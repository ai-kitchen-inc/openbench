import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SOURCE_ACCEPT, SourcePanel } from "./App";
import { ToastProvider } from "./Toast";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderSourcePanel() {
  const attachments: unknown[] = [];
  return render(
    <ToastProvider durationMs={0}>
      <SourcePanel
        sessionId="session-1"
        onAttachmentsChange={(nextAttachments) => {
          attachments.splice(0, attachments.length, ...nextAttachments);
        }}
      />
    </ToastProvider>,
  );
}

describe("SourcePanel discovery flow", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not request discovery while typing", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/chat/sources/session-1")) {
        return jsonResponse([]);
      }
      return jsonResponse({ query: "", results: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSourcePanel();

    await screen.findByText("Added sources");
    const discoveryInput = screen.getByPlaceholderText("Search the web for sources");
    await userEvent.type(discoveryInput, "test");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/chat/sources/session-1");
  });

  it("requests discovery on Search button click and renders results", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/chat/sources/session-1") {
        return jsonResponse([]);
      }
      if (url === "/chat/sources/discover?q=climate") {
        return jsonResponse({
          query: "climate",
          results: [
            {
              id: "r1",
              title: "Climate report",
              url: "https://example.com/report",
              domain: "example.com",
              snippet: "A useful report summary",
              faviconUrl: "https://example.com/favicon.ico",
            },
          ],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSourcePanel();

    const discoveryInput = await screen.findByPlaceholderText("Search the web for sources");
    await userEvent.type(discoveryInput, "climate");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("Climate report")).toBeInTheDocument();
    expect(screen.getByText("example.com")).toBeInTheDocument();
    expect(screen.getByText("A useful report summary")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/chat/sources/discover?q=climate");
  });

  it("requests discovery on Enter", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/chat/sources/session-1") {
        return jsonResponse([]);
      }
      if (url === "/chat/sources/discover?q=policy") {
        return jsonResponse({ query: "policy", results: [] });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSourcePanel();

    const discoveryInput = await screen.findByPlaceholderText("Search the web for sources");
    await userEvent.type(discoveryInput, "policy{enter}");

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/chat/sources/discover?q=policy"),
    );
  });

  it("prevents duplicate searches for the same submitted query", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/chat/sources/session-1") {
        return jsonResponse([]);
      }
      if (url === "/chat/sources/discover?q=energy") {
        return jsonResponse({ query: "energy", results: [] });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSourcePanel();

    const discoveryInput = await screen.findByPlaceholderText("Search the web for sources");
    await userEvent.type(discoveryInput, "energy");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText('No results for "energy".');
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("allows selecting search results and adding selected links as sources", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/chat/sources/session-1" && (!init || init.method === undefined)) {
        return jsonResponse([]);
      }
      if (url === "/chat/sources/discover?q=notebooklm") {
        return jsonResponse({
          query: "notebooklm",
          results: [
            {
              id: "r1",
              title: "NotebookLM overview",
              url: "https://example.com/notebooklm",
              domain: "example.com",
              snippet: "Overview snippet",
            },
            {
              id: "r2",
              title: "NotebookLM tips",
              url: "https://docs.example.com/tips",
              domain: "docs.example.com",
              snippet: "Tips snippet",
            },
          ],
        });
      }
      if (url === "/chat/sources/session-1/url" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return jsonResponse({
          id: body.url.includes("tips") ? "source-2" : "source-1",
          sessionId: "session-1",
          name: body.url.includes("tips") ? "NotebookLM tips" : "NotebookLM overview",
          kind: "url",
          mimeType: "text/html",
          status: "ready",
          error: null,
          sizeBytes: 1200,
          createdAt: "2026-05-07T00:00:00+00:00",
          url: body.url,
          extractedText: "Fetched web source text",
          metadata: null,
        });
      }
      if (url === "/chat/sources/session-1" && init?.method === undefined) {
        return jsonResponse([
          {
            id: "source-1",
            sessionId: "session-1",
            name: "NotebookLM overview",
            kind: "url",
            mimeType: "text/html",
            status: "ready",
            error: null,
            sizeBytes: 1200,
            createdAt: "2026-05-07T00:00:00+00:00",
            url: "https://example.com/notebooklm",
            metadata: null,
          },
          {
            id: "source-2",
            sessionId: "session-1",
            name: "NotebookLM tips",
            kind: "url",
            mimeType: "text/html",
            status: "ready",
            error: null,
            sizeBytes: 1300,
            createdAt: "2026-05-07T00:00:00+00:00",
            url: "https://docs.example.com/tips",
            metadata: null,
          },
        ]);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSourcePanel();

    const discoveryInput = await screen.findByPlaceholderText("Search the web for sources");
    await userEvent.type(discoveryInput, "notebooklm");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    const checkboxes = await screen.findAllByRole("checkbox");
    await userEvent.click(checkboxes[0]);
    await userEvent.click(checkboxes[1]);
    await userEvent.click(screen.getByRole("button", { name: "Add selected sources" }));

    await screen.findByText("NotebookLM overview");
    await screen.findByText("NotebookLM tips");
    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/sources/session-1/url",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("does not render the old local source search UI", async () => {
    const fetchMock = vi.fn(async () => jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    renderSourcePanel();

    await screen.findByText("Discover sources");
    expect(screen.queryByPlaceholderText("Search inside added sources")).not.toBeInTheDocument();
  });

  it("uses the shared source accept policy for the source upload input", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    renderSourcePanel();

    await screen.findByText("Added sources");
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput?.getAttribute("accept")).toBe(SOURCE_ACCEPT);
  });
});
