import { render, screen } from "@testing-library/react";
import { ToastProvider } from "../Toast";
import { SourcePanel } from "./SourcePanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const READY_SOURCE = {
  id: "src-1",
  sessionId: "session-1",
  name: "laporan.pdf",
  kind: "document",
  mimeType: "application/pdf",
  status: "ready",
  error: null,
  sizeBytes: 1024,
  createdAt: "2026-08-31T00:00:00Z",
  url: null,
  extractedText: "isi laporan",
};

function stubFetch(sources: unknown[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/auth/drive/status") {
        return jsonResponse({ configured: false, connected: false });
      }
      if (url === "/chat/sources/session-1") return jsonResponse(sources);
      throw new Error(`Unexpected fetch: ${url}`);
    }),
  );
}

describe("SourcePanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("offers file, text, and URL sources for an active session", async () => {
    stubFetch([READY_SOURCE]);
    const onAttachmentsChange = vi.fn();
    render(
      <ToastProvider>
        <SourcePanel sessionId="session-1" onAttachmentsChange={onAttachmentsChange} />
      </ToastProvider>,
    );
    expect(await screen.findByText("laporan.pdf")).toBeInTheDocument();
    expect(screen.getByText("Unggah Dokumen")).toBeInTheDocument();
    expect(screen.getByText("Tempel Teks")).toBeInTheDocument();
    expect(screen.getByText("Tambah URL")).toBeInTheDocument();
    // Ready sources ride along as composer attachments.
    expect(onAttachmentsChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ id: "src-1", name: "laporan.pdf" }),
    ]);
  });

  it("shows a hint and no source list before a session exists", async () => {
    stubFetch();
    render(
      <ToastProvider>
        <SourcePanel sessionId={null} onAttachmentsChange={() => {}} />
      </ToastProvider>,
    );
    expect(
      await screen.findByText("Mulai percakapan untuk menambah sumber."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Unggah Dokumen")).toBeNull();
  });
});
