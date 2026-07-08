import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  DashboardArtifactPanel,
  DIRECT_UPLOAD_THRESHOLD_BYTES,
  findLatestDashboard,
  SOURCE_ACCEPT,
  SourcePanel,
  uploadComposerAttachment,
} from "./App";
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

  it("uploads small composer files through the source multipart endpoint", async () => {
    const openedRequests: Array<{ method: string; url: string }> = [];
    class MockXMLHttpRequest {
      status = 200;
      statusText = "OK";
      response: unknown = {
        id: "source-small",
        sessionId: "session-1",
        name: "small.png",
        kind: "image",
        mimeType: "image/png",
        status: "processing",
        error: null,
        sizeBytes: 4,
        createdAt: "2026-05-07T00:00:00+00:00",
        url: "gs://test/uploads/default/session-1/file-small/small.png",
        metadata: { fileId: "file-small", parseStatus: "queued" },
      };
      responseType = "";
      upload = {
        addEventListener: vi.fn((eventName: string, listener: (event: ProgressEvent) => void) => {
          if (eventName === "progress") {
            listener({ lengthComputable: true, loaded: 4, total: 4 } as ProgressEvent);
          }
        }),
      };
      private loadListener: (() => void) | null = null;

      open(method: string, url: string) {
        openedRequests.push({ method, url });
      }

      setRequestHeader() {}

      addEventListener(eventName: string, listener: () => void) {
        if (eventName === "load") this.loadListener = listener;
      }

      send() {
        this.loadListener?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", MockXMLHttpRequest);

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/chat/uploads/file-small?sessionId=session-1&includeText=true") {
        return jsonResponse({
          fileId: "file-small",
          status: "ready",
          source: {
            id: "source-small",
            sessionId: "session-1",
            name: "small.png",
            kind: "image",
            mimeType: "image/png",
            status: "ready",
            error: null,
            sizeBytes: 4,
            createdAt: "2026-05-07T00:00:00+00:00",
            url: "/uploads/file-small/small.png",
            extractedText: "sam_segmentation MCP path: /general-chat/uploads/file-small/small.png",
            metadata: {
              fileId: "file-small",
              parseStatus: "ready",
              samSegmentationPath: "/general-chat/uploads/file-small/small.png",
            },
          },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const attachment = await uploadComposerAttachment(
      new File(["tiny"], "small.png", { type: "image/png" }),
      "session-1",
      vi.fn(),
    );

    expect(openedRequests).toContainEqual({ method: "POST", url: "/chat/upload" });
    expect(attachment.path).toBe("/general-chat/uploads/file-small/small.png");
    expect(attachment.extractedText).toContain("sam_segmentation MCP path");
  });

  it("uploads large composer files through direct GCS and polls with extracted text", async () => {
    const openedRequests: Array<{ method: string; url: string }> = [];
    class MockXMLHttpRequest {
      status = 200;
      statusText = "OK";
      response: unknown = {};
      responseType = "";
      upload = {
        addEventListener: vi.fn((eventName: string, listener: (event: ProgressEvent) => void) => {
          if (eventName === "progress") {
            listener({ lengthComputable: true, loaded: 10, total: 10 } as ProgressEvent);
          }
        }),
      };
      private loadListener: (() => void) | null = null;

      open(method: string, url: string) {
        openedRequests.push({ method, url });
      }

      setRequestHeader() {}

      addEventListener(eventName: string, listener: () => void) {
        if (eventName === "load") this.loadListener = listener;
      }

      send() {
        this.loadListener?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", MockXMLHttpRequest);

    const processingSource = {
      id: "source-large",
      sessionId: "session-1",
      name: "large.pdf",
      kind: "pdf",
      mimeType: "application/pdf",
      status: "processing",
      error: null,
      sizeBytes: DIRECT_UPLOAD_THRESHOLD_BYTES + 1,
      createdAt: "2026-05-07T00:00:00+00:00",
      url: null,
      metadata: { fileId: "file-large", parseStatus: "queued" },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/chat/uploads/initiate" && init?.method === "POST") {
        return jsonResponse({
          fileId: "file-large",
          uploadUrl: "https://storage.googleapis.test/upload/session",
          method: "PUT",
          headers: { "Content-Type": "application/pdf" },
          source: processingSource,
        });
      }
      if (url === "/chat/uploads/complete" && init?.method === "POST") {
        return jsonResponse({
          fileId: "file-large",
          status: "queued",
          source: processingSource,
        });
      }
      if (url === "/chat/uploads/file-large?sessionId=session-1&includeText=true") {
        return jsonResponse({
          fileId: "file-large",
          status: "ready",
          source: {
            ...processingSource,
            status: "ready",
            url: "/uploads/file-large/large.pdf",
            extractedText: "full extracted pdf text",
            metadata: { fileId: "file-large", parseStatus: "ready" },
          },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["large"], "large.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: DIRECT_UPLOAD_THRESHOLD_BYTES + 1 });
    const attachment = await uploadComposerAttachment(file, "session-1", vi.fn());

    expect(openedRequests).toContainEqual({
      method: "PUT",
      url: "https://storage.googleapis.test/upload/session",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/uploads/file-large?sessionId=session-1&includeText=true",
    );
    expect(attachment.extractedText).toBe("full extracted pdf text");
  });

  it("uploads large files through the direct GCS upload flow", async () => {
    const openedRequests: Array<{ method: string; url: string }> = [];
    class MockXMLHttpRequest {
      status = 200;
      statusText = "OK";
      response: unknown = {};
      responseType = "";
      upload = {
        addEventListener: vi.fn((eventName: string, listener: (event: ProgressEvent) => void) => {
          if (eventName === "progress") {
            this.progressListener = listener;
          }
        }),
      };
      private loadListener: (() => void) | null = null;
      private errorListener: (() => void) | null = null;
      private progressListener: ((event: ProgressEvent) => void) | null = null;

      open(method: string, url: string) {
        openedRequests.push({ method, url });
      }

      setRequestHeader() {}

      addEventListener(eventName: string, listener: () => void) {
        if (eventName === "load") this.loadListener = listener;
        if (eventName === "error") this.errorListener = listener;
      }

      send() {
        this.progressListener?.({ lengthComputable: true, loaded: 10, total: 10 } as ProgressEvent);
        this.loadListener?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", MockXMLHttpRequest);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/chat/sources/session-1" && !init?.method) {
        return jsonResponse([]);
      }
      if (url === "/chat/uploads/initiate" && init?.method === "POST") {
        return jsonResponse({
          fileId: "file-large",
          uploadUrl: "https://storage.googleapis.test/upload/session",
          method: "PUT",
          headers: { "Content-Type": "application/pdf" },
          source: {
            id: "source-large",
            sessionId: "session-1",
            name: "large.pdf",
            kind: "pdf",
            mimeType: "application/pdf",
            status: "processing",
            error: null,
            sizeBytes: DIRECT_UPLOAD_THRESHOLD_BYTES + 1,
            createdAt: "2026-05-07T00:00:00+00:00",
            url: null,
            metadata: { fileId: "file-large", parseStatus: "queued" },
          },
        });
      }
      if (url === "/chat/uploads/complete" && init?.method === "POST") {
        return jsonResponse({
          fileId: "file-large",
          status: "ready",
          source: {
            id: "source-large",
            sessionId: "session-1",
            name: "large.pdf",
            kind: "pdf",
            mimeType: "application/pdf",
            status: "ready",
            error: null,
            sizeBytes: DIRECT_UPLOAD_THRESHOLD_BYTES + 1,
            createdAt: "2026-05-07T00:00:00+00:00",
            url: "/uploads/file-large/large.pdf",
            extractedText: "ready",
            metadata: { fileId: "file-large", parseStatus: "ready" },
          },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSourcePanel();
    await screen.findByText("Added sources");
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    const file = new File(["large"], "large.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: DIRECT_UPLOAD_THRESHOLD_BYTES + 1 });

    await userEvent.upload(fileInput!, file);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/chat/uploads/complete", expect.anything()));
    expect(fetchMock).toHaveBeenCalledWith("/chat/uploads/initiate", expect.anything());
    expect(openedRequests).toContainEqual({
      method: "PUT",
      url: "https://storage.googleapis.test/upload/session",
    });
    expect(fetchMock).not.toHaveBeenCalledWith("/chat/upload", expect.anything());
  });

  it("polls wrapped direct upload status responses and updates processing sources", async () => {
    const openedRequests: Array<{ method: string; url: string }> = [];
    class MockXMLHttpRequest {
      status = 200;
      statusText = "OK";
      response: unknown = {};
      responseType = "";
      upload = {
        addEventListener: vi.fn(),
      };
      private loadListener: (() => void) | null = null;

      open(method: string, url: string) {
        openedRequests.push({ method, url });
      }

      setRequestHeader() {}

      addEventListener(eventName: string, listener: () => void) {
        if (eventName === "load") this.loadListener = listener;
      }

      send() {
        this.loadListener?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", MockXMLHttpRequest);

    const processingSource = {
      id: "source-large",
      sessionId: "session-1",
      name: "large.pdf",
      kind: "pdf",
      mimeType: "application/pdf",
      status: "processing",
      error: null,
      sizeBytes: DIRECT_UPLOAD_THRESHOLD_BYTES + 1,
      createdAt: "2026-05-07T00:00:00+00:00",
      url: null,
      metadata: { fileId: "file-large", parseStatus: "queued" },
    };
    const readySource = {
      ...processingSource,
      status: "ready",
      url: "/uploads/file-large/large.pdf",
      extractedText: "ready text",
      metadata: { fileId: "file-large", parseStatus: "ready" },
    };
    let sourceListCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/chat/sources/session-1" && !init?.method) {
        sourceListCalls += 1;
        return jsonResponse(sourceListCalls === 1 ? [] : [processingSource]);
      }
      if (url === "/chat/uploads/initiate" && init?.method === "POST") {
        return jsonResponse({
          fileId: "file-large",
          uploadUrl: "https://storage.googleapis.test/upload/session",
          method: "PUT",
          headers: { "Content-Type": "application/pdf" },
          source: processingSource,
        });
      }
      if (url === "/chat/uploads/complete" && init?.method === "POST") {
        return jsonResponse({
          fileId: "file-large",
          status: "queued",
          source: processingSource,
        });
      }
      if (url === "/chat/uploads/file-large?sessionId=session-1") {
        return jsonResponse({
          fileId: "file-large",
          status: "ready",
          source: readySource,
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSourcePanel();
    await screen.findByText("Added sources");
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    const file = new File(["large"], "large.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: DIRECT_UPLOAD_THRESHOLD_BYTES + 1 });

    await userEvent.upload(fileInput!, file);

    expect(openedRequests).toContainEqual({
      method: "PUT",
      url: "https://storage.googleapis.test/upload/session",
    });
    expect(await screen.findByText("Processing: queued")).toBeInTheDocument();
    await waitFor(
      () =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/chat/uploads/file-large?sessionId=session-1",
        ),
      { timeout: 4000 },
    );
    expect(await screen.findByText("/uploads/file-large/large.pdf")).toBeInTheDocument();
  });

  it("renders processing sources while direct uploads are being parsed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse([
          {
            id: "source-processing",
            sessionId: "session-1",
            name: "big-notes.pdf",
            kind: "pdf",
            mimeType: "application/pdf",
            status: "processing",
            error: null,
            sizeBytes: DIRECT_UPLOAD_THRESHOLD_BYTES + 1,
            createdAt: "2026-05-07T00:00:00+00:00",
            url: null,
            metadata: { parseStatus: "queued" },
          },
        ]),
      ),
    );

    renderSourcePanel();

    expect(await screen.findByText("big-notes.pdf")).toBeInTheDocument();
    expect(screen.getByText("Processing: queued")).toBeInTheDocument();
    expect(screen.getByText("Queued for parsing")).toBeInTheDocument();
  });
});

describe("findLatestDashboard", () => {
  const baseMessage = {
    role: "assistant" as const,
    content: "reply",
    timestamp: "2026-07-08T10:00:00Z",
    status: "complete" as const,
  };

  it("does not throw on persisted stub surfaces without components", () => {
    // Regression: opening a past chat crashed with
    // `can't access property "values", a.components is undefined`.
    const messages = [
      {
        ...baseMessage,
        id: "m-1",
        surfaces: [{ surfaceId: "s-stub" } as never],
      },
    ];

    expect(() => findLatestDashboard(messages)).not.toThrow();
    expect(findLatestDashboard(messages)).toBeNull();
  });

  it("finds the dashboard in a Map-based surface", () => {
    const messages = [
      {
        ...baseMessage,
        id: "m-1",
        surfaces: [
          {
            surfaceId: "s-1",
            catalogId: "openbench",
            components: new Map([
              [
                "root",
                {
                  id: "root",
                  component: "ObDashboardFrame",
                  title: "Sales Dashboard",
                  dashboardUrl: "/downloads/sales.html",
                },
              ],
            ]),
            dataModel: {},
          },
        ],
      },
    ];

    const artifact = findLatestDashboard(messages);
    expect(artifact).not.toBeNull();
    expect(artifact?.title).toBe("Sales Dashboard");
    expect(artifact?.url).toBe("/downloads/sales.html");
    expect(artifact?.surface.components.get("root")).toBeDefined();
  });

  it("returns null when no dashboard components exist", () => {
    const messages = [
      {
        ...baseMessage,
        id: "m-1",
        surfaces: [
          {
            surfaceId: "s-1",
            catalogId: "openbench",
            components: new Map([
              ["root", { id: "root", component: "Text", text: "plain" }],
            ]),
            dataModel: {},
          },
        ],
      },
    ];

    expect(findLatestDashboard(messages)).toBeNull();
  });
});

describe("DashboardArtifactPanel", () => {
  it("renders the A2UI dashboard surface when ViewModel and dashboardUrl both exist", () => {
    const viewModel = {
      title: "Sales Dashboard",
      description: "Native dashboard data.",
      kpis: [{ label: "Revenue", value: 1200 }],
      sections: [],
      datasets: {},
    };
    const artifact = {
      messageId: "msg-1",
      title: "Sales Dashboard",
      url: "/downloads/sales.html",
      fileName: "sales.html",
      summary: "Native dashboard data.",
      surface: {
        surfaceId: "msg-1-dashboard-artifact",
        catalogId: "openbench",
        components: new Map([
          [
            "root",
            {
              id: "root",
              component: "ObDashboardFrame",
              title: "Sales Dashboard",
              dashboardUrl: "/downloads/sales.html",
              viewModel,
            },
          ],
        ]),
        dataModel: {},
      },
    };

    const { container } = render(
      <DashboardArtifactPanel artifact={artifact} onClose={vi.fn()} />,
    );

    expect(screen.getAllByText("Sales Dashboard").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-dashboard-renderer="a2ui"]')).not.toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("renders the A2UI dashboard surface when ViewModel is inside legacy properties", () => {
    const viewModel = {
      title: "Dashboard Penjualan Kopi",
      description: "Native dashboard data.",
      kpis: [{ label: "Revenue", value: 1200 }],
      sections: [],
      datasets: {},
    };
    const artifact = {
      messageId: "msg-1",
      title: "Dashboard Penjualan Kopi",
      url: "/downloads/kopi.html",
      fileName: "kopi.html",
      summary: "Native dashboard data.",
      surface: {
        surfaceId: "msg-1-dashboard-artifact",
        catalogId: "openbench",
        components: new Map([
          [
            "root",
            {
              id: "root",
              component: "ObDashboardFrame",
              title: "Dashboard Penjualan Kopi",
              dashboardUrl: "/downloads/kopi.html",
              properties: { viewModel },
            },
          ],
        ]),
        dataModel: {},
      },
    };

    const { container } = render(
      <DashboardArtifactPanel artifact={artifact} onClose={vi.fn()} />,
    );

    expect(screen.getAllByText("Dashboard Penjualan Kopi").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-dashboard-renderer="a2ui"]')).not.toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
  });
});
