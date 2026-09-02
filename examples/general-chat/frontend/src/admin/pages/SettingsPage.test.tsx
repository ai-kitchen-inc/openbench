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
  values: { llm_model: "gemini-3.5-flash", vlm_model: "vlm-x", vector_store: "postgres" },
  options: {
    llm_model: ["gemini-3.5-flash", "gemini-2.5-pro"],
    vlm_model: ["vlm-x"],
    vector_store: ["postgres", "pinecone"],
  },
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
});
