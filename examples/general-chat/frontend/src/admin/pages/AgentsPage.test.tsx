import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../Toast";
import { AgentsPage } from "./AgentsPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const AGENT = {
  id: "analis-keuangan",
  name: "Analis Keuangan",
  description: "Laporan keuangan, anggaran, pajak.",
  enabled: true,
  persona: {},
  model: "gemini-2.5-pro",
  temperature: null,
  skills: ["query-explorer"],
  customSkillIds: [],
  useSources: true,
  escalationAgentId: "",
  confidenceThreshold: 0.5,
  createdAt: "2026-08-24T00:00:00Z",
  createdBy: "admin@x.co",
  updatedAt: "2026-08-24T00:00:00Z",
};

const OPTIONS = {
  models: ["gemini-2.5-flash", "gemini-2.5-pro"],
  sdkSkills: ["export-excel", "query-explorer"],
  customSkills: [],
  escalationTargets: [{ id: "analis-keuangan", name: "Analis Keuangan" }],
  personaTemplates: [
    {
      id: "strict",
      name: "Ketat",
      description: "Hanya menjawab dari sumber.",
      soul: "SOUL ketat",
      style: "STYLE ketat",
      agents: "AGENTS ketat",
      goal: "GOAL ketat",
      sourceContextLabel: "Sumber",
    },
  ],
  activeEmbedding: { provider: "google", model: "gemini-embedding-001", dimension: 1536 },
  defaults: { confidenceThreshold: 0.5 },
};

describe("AgentsPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists agents from the API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/admin/agents") return jsonResponse({ agents: [AGENT] });
        if (url === "/admin/agents/options") return jsonResponse(OPTIONS);
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <AgentsPage />
      </ToastProvider>,
    );
    expect(await screen.findByText("Analis Keuangan")).toBeDefined();
    expect(screen.getByText(/1 agen terdaftar/)).toBeDefined();
    expect(screen.getByText(/Laporan keuangan/)).toBeDefined();
  });

  it("creates an agent via POST", async () => {
    const postBodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/admin/agents" && init?.method === "POST") {
          postBodies.push(JSON.parse(String(init.body)));
          return jsonResponse(AGENT, 201);
        }
        if (url === "/admin/agents") return jsonResponse({ agents: [] });
        if (url === "/admin/agents/options") return jsonResponse(OPTIONS);
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <AgentsPage />
      </ToastProvider>,
    );
    await screen.findByText(/Belum ada agen/);
    await userEvent.type(screen.getByLabelText("Nama agen"), "Analis Keuangan");
    await userEvent.type(
      screen.getByLabelText("Deskripsi agen"),
      "Laporan keuangan, anggaran, pajak.",
    );
    await userEvent.click(screen.getByText("Buat agen"));
    await waitFor(() => expect(postBodies).toHaveLength(1));
    expect(postBodies[0]).toEqual({
      name: "Analis Keuangan",
      description: "Laporan keuangan, anggaran, pajak.",
    });
  });

  it("shows the full source manager (incl. upload) in the agent detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/admin/agents") return jsonResponse({ agents: [AGENT] });
        if (url === "/admin/agents/options") return jsonResponse(OPTIONS);
        if (url === "/admin/agents/analis-keuangan/sources") {
          return jsonResponse({
            sources: [{ id: "src-1", name: "kebijakan.pdf", kind: "document" }],
          });
        }
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <AgentsPage />
      </ToastProvider>,
    );
    await userEvent.click(await screen.findByText("Kelola"));
    expect(await screen.findByText("kebijakan.pdf")).toBeDefined();
    expect(screen.getByText("Unggah Dokumen")).toBeDefined();
    expect(screen.getByText("Tempel Teks")).toBeDefined();
    expect(screen.getByText("Tambah URL")).toBeDefined();
  });

  it("puts persona first in the detail and prefills from a template", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/admin/agents") return jsonResponse({ agents: [AGENT] });
        if (url === "/admin/agents/options") return jsonResponse(OPTIONS);
        if (url === "/admin/agents/analis-keuangan/sources") {
          return jsonResponse({ sources: [] });
        }
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <AgentsPage />
      </ToastProvider>,
    );
    await userEvent.click(await screen.findByText("Kelola"));
    const detail = (await screen.findByText("Persona")).closest(
      ".panel-section__body",
    ) as HTMLElement;
    // Persona block renders before the Profil block.
    const labels = Array.from(detail.querySelectorAll(".cap-row__label")).map(
      (node) => node.textContent,
    );
    expect(labels.indexOf("Persona")).toBeLessThan(labels.indexOf("Profil"));

    await userEvent.selectOptions(screen.getByLabelText("Templat persona"), "strict");
    expect(screen.getByLabelText("SOUL — identitas agen")).toHaveValue("SOUL ketat");
    expect(screen.getByLabelText("STYLE — gaya menjawab")).toHaveValue("STYLE ketat");
    expect(screen.getByLabelText("AGENTS — aturan kerja")).toHaveValue("AGENTS ketat");
    expect(screen.getByLabelText("Goal (opsional)")).toHaveValue("GOAL ketat");
  });

  it("requires a description before enabling create", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/admin/agents") return jsonResponse({ agents: [] });
        if (url === "/admin/agents/options") return jsonResponse(OPTIONS);
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <AgentsPage />
      </ToastProvider>,
    );
    await screen.findByText(/Belum ada agen/);
    await userEvent.type(screen.getByLabelText("Nama agen"), "Analis");
    expect((screen.getByText("Buat agen") as HTMLButtonElement).disabled).toBe(true);
  });
});
