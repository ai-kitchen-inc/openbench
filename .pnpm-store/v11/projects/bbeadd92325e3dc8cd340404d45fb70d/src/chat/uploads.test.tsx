import { DIRECT_UPLOAD_THRESHOLD_BYTES, uploadComposerAttachment } from "./uploads";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("uploadComposerAttachment", () => {
  afterEach(() => {
    vi.restoreAllMocks();
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
});
