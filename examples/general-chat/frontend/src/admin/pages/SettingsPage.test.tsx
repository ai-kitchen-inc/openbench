import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../Toast";
import { SettingsPage } from "./SettingsPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const RUNTIME = {
  values: {
    llm_model: "gemini-3.5-flash",
    vlm_model: "vlm-x",
    vector_store: "postgres",
    embedding_model: "gemini-embedding-001",
  },
  options: {
    llm_model: ["gemini-3.5-flash", "gemini-2.5-pro"],
    vlm_model: ["vlm-x"],
    vector_store: ["postgres", "pinecone"],
    embedding_model: ["gemini-embedding-001", "emb-2"],
  },
};

const REINDEX_IDLE = {
  status: "idle",
  total: 0,
  done: 0,
  ready: 0,
  failed: 0,
  skipped: 0,
  startedAt: "",
  finishedAt: "",
  error: "",
  embeddingModel: "",
};

const REINDEX_RUNNING = {
  ...REINDEX_IDLE,
  status: "running",
  total: 3,
  startedAt: "2026-09-10T00:00:00Z",
  embeddingModel: "gemini-embedding-001",
};

const CATALOG = {
  chatModels: [
    { id: "gemini-3.5-flash", label: "gemini-3.5-flash" },
    { id: "gemini-2.5-pro", label: "gemini-2.5-pro" },
  ],
  embeddingModels: [
    { id: "gemini-embedding-001", provider: "google", dimension: 1536, label: "gemini-embedding-001" },
  ],
};

const PRIVACY = { retentionDays: 30, piiRedaction: false };

function stubFetch(overrides: {
  onPutModels?: (body: unknown) => Response;
  onPutRuntime?: (body: unknown) => Response;
  onPostReindex?: () => Response;
} = {}) {
  return vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/admin/runtime-settings" && init?.method === "PUT") {
        return (
          overrides.onPutRuntime?.(JSON.parse(String(init.body))) ?? jsonResponse(RUNTIME)
        );
      }
      if (url === "/admin/runtime-settings") return jsonResponse(RUNTIME);
      if (url === "/admin/models" && init?.method === "PUT") {
        return (
          overrides.onPutModels?.(JSON.parse(String(init.body))) ?? jsonResponse(CATALOG)
        );
      }
      if (url === "/admin/models") return jsonResponse(CATALOG);
      if (url === "/admin/privacy") return jsonResponse(PRIVACY);
      if (url === "/admin/sources/reindex" && init?.method === "POST") {
        return overrides.onPostReindex?.() ?? jsonResponse(REINDEX_RUNNING, 202);
      }
      if (url === "/admin/sources/reindex") return jsonResponse(REINDEX_IDLE);
      throw new Error(`Unexpected fetch: ${url}`);
    }),
  );
}

describe("SettingsPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the model catalog with the default marked", async () => {
    stubFetch();
    render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
    expect(await screen.findByText("Katalog Model")).toBeInTheDocument();
    expect(screen.getByText("bawaan")).toBeInTheDocument();
    // The active default cannot be deleted.
    expect(screen.getByLabelText("Hapus gemini-3.5-flash")).toBeDisabled();
    expect(screen.getByLabelText("Hapus gemini-2.5-pro")).toBeEnabled();
    expect(screen.getByText(/gemini-embedding-001 · google · dim 1536/)).toBeInTheDocument();
  });

  it("adds a chat model via whole-object PUT", async () => {
    const putBodies: unknown[] = [];
    stubFetch({
      onPutModels: (body) => {
        putBodies.push(body);
        return jsonResponse({
          ...CATALOG,
          chatModels: [...CATALOG.chatModels, { id: "model-baru", label: "model-baru" }],
        });
      },
    });
    render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
    await screen.findByText("Katalog Model");
    await userEvent.type(screen.getByLabelText("ID model chat"), "model-baru");
    await userEvent.click(screen.getByText("Tambah model chat"));
    await waitFor(() => expect(putBodies).toHaveLength(1));
    expect(putBodies[0]).toEqual({
      chatModels: [...CATALOG.chatModels, { id: "model-baru", label: "model-baru" }],
    });
    expect((await screen.findAllByText("model-baru")).length).toBeGreaterThan(0);
  });

  it("changes the default through runtime settings", async () => {
    const runtimePuts: unknown[] = [];
    stubFetch({
      onPutRuntime: (body) => {
        runtimePuts.push(body);
        return jsonResponse({
          ...RUNTIME,
          values: { ...RUNTIME.values, llm_model: "gemini-2.5-pro" },
        });
      },
    });
    render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
    await screen.findByText("Katalog Model");
    await userEvent.click(screen.getByText("Jadikan bawaan"));
    await waitFor(() => expect(runtimePuts).toEqual([{ llm_model: "gemini-2.5-pro" }]));
  });

  it("offers a source reindex with the default description when idle", async () => {
    stubFetch();
    render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
    expect(
      await screen.findByText(/Bangun ulang vektor sumber bersama, grup, dan agen/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Indeks ulang sumber" })).toBeEnabled();
    expect(screen.queryByText(/Memproses|Selesai:|Gagal:/)).not.toBeInTheDocument();
  });

  it("starts a reindex after confirmation and shows progress", async () => {
    const posts: number[] = [];
    stubFetch({
      onPostReindex: () => {
        posts.push(1);
        return jsonResponse(REINDEX_RUNNING, 202);
      },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Indeks ulang sumber" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Mengindeks..." })).toBeDisabled();
    expect(screen.getByText("Memproses 0/3 sumber...")).toBeInTheDocument();
  });

  it("does nothing when the reindex confirmation is declined", async () => {
    const posts: number[] = [];
    stubFetch({
      onPostReindex: () => {
        posts.push(1);
        return jsonResponse(REINDEX_RUNNING, 202);
      },
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Indeks ulang sumber" }));
    expect(posts).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Indeks ulang sumber" })).toBeEnabled();
  });

  it("keeps the embedding-change warning next to the reindex button", async () => {
    stubFetch({
      onPutRuntime: (body) =>
        jsonResponse({
          ...RUNTIME,
          values: { ...RUNTIME.values, ...(body as Record<string, string>) },
          embedding: { ok: true, warning: "Vektor lama tidak cocok. Indeks ulang sumber." },
        }),
    });
    render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
    await screen.findByText("Katalog Model");
    await userEvent.selectOptions(screen.getByLabelText("Model Embedding"), "emb-2");
    // Toast and row both carry the warning; the row keeps it after the toast fades.
    await waitFor(() =>
      expect(screen.getAllByText(/Vektor lama tidak cocok/).length).toBeGreaterThan(0),
    );
    expect(
      screen.queryByText(/Bangun ulang vektor sumber bersama, grup, dan agen/),
    ).not.toBeInTheDocument();
  });
});
