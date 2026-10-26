import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../Toast";
import { PersonaPage } from "./PersonaPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("PersonaPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders empty Agent Spec inputs with Indonesian instructional placeholders", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/admin/persona") {
        return jsonResponse({
          settings: null,
          source: "files",
          active: { soul_chars: 10, style_chars: 20, agents_chars: 30, total_chars: 60 },
        });
      }
      if (url === "/admin/persona/templates") {
        return jsonResponse({ templates: [] });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ToastProvider durationMs={0}>
        <PersonaPage />
      </ToastProvider>,
    );

    expect(await screen.findByText("Sunting Spesifikasi Agen")).toBeInTheDocument();
    expect(screen.getByText("Persona - identitas dan peran")).toBeInTheDocument();
    expect(
      screen.getByText("Aturan Gaya - bahasa, nada, dan format jawaban"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Batasan Pengaman - akurasi, verifikasi, dan keamanan"),
    ).toBeInTheDocument();
    expect(screen.getByText("Aturan - perilaku yang wajib diikuti")).toBeInTheDocument();
    expect(
      screen.getByText("Cakupan / Kemampuan - hal yang dapat dikerjakan agen"),
    ).toBeInTheDocument();
    expect(screen.getByText("Larangan - hal yang tidak boleh dilakukan agen")).toBeInTheDocument();
    expect(screen.getByLabelText(/Batasan Pengaman/)).toHaveValue("");
    expect(
      screen.getByPlaceholderText(
        "Aturan untuk data yang kurang, asumsi, ketidakpastian, verifikasi, dan dasar fakta...",
      ),
    ).toBeInTheDocument();
  });

  it("hides built-in default rules and only shows the Rules placeholder", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/admin/persona") {
        return jsonResponse({
          settings: {
            template: "",
            soul: "",
            style: "",
            agents: `# Agent Spec

## Rules

### General Q&A
Answer general questions directly. Use optional user-provided context when it is helpful, but do not require context before answering.

### Tool Usage Rules
- Use enabled MCP tools when the user asks for tool-backed work or when a tool is clearly useful for the task.
- Explain tool results in plain language.
- Do not claim that optional source context is mandatory for unrelated questions.

## File Deliverables
When the user asks for a file, actually produce one by calling the matching tool.`,
            goal: "",
            source_context_label: "",
          },
          source: "db",
          active: {},
        });
      }
      if (url === "/admin/persona/templates") {
        return jsonResponse({ templates: [] });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ToastProvider durationMs={0}>
        <PersonaPage />
      </ToastProvider>,
    );

    const rulesInput = await screen.findByLabelText(/Aturan - perilaku/);
    expect(rulesInput).toHaveValue("");
    expect(
      screen.getByPlaceholderText(
        "Aturan operasional yang harus dipatuhi asisten selama percakapan...",
      ),
    ).toBeInTheDocument();
  });

  it("saves the Agent Spec through the existing soul/style/agents payload", async () => {
    const putBodies: unknown[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/admin/persona" && (!init || !init.method)) {
        return jsonResponse({
          settings: null,
          source: "files",
          active: {},
        });
      }
      if (url === "/admin/persona/templates") {
        return jsonResponse({ templates: [] });
      }
      if (url === "/admin/persona" && init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        putBodies.push(body);
        return jsonResponse({
          ok: true,
          settings: {
            template: "",
            soul: body.soul,
            style: body.style,
            agents: body.agents,
            goal: body.goal,
            source_context_label: "",
          },
          source: "db",
          active: { soul_chars: 1, style_chars: 1, agents_chars: 1, total_chars: 3 },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ToastProvider durationMs={0}>
        <PersonaPage />
      </ToastProvider>,
    );

    await userEvent.clear(await screen.findByLabelText(/Batasan Pengaman/));
    await userEvent.type(screen.getByLabelText(/Batasan Pengaman/), "Jangan mengarang.");
    await userEvent.click(screen.getByRole("button", { name: "Simpan Spesifikasi Agen" }));

    await waitFor(() => expect(putBodies).toHaveLength(1));
    expect(putBodies[0]).toMatchObject({
      soul: expect.stringContaining("# General Chat Assistant"),
      style: expect.stringContaining("# Communication Style"),
      agents: expect.stringContaining("## Guardrails\nJangan mengarang."),
    });
    expect((putBodies[0] as { agents: string }).agents).toContain("## Scope / Capabilities");
    expect((putBodies[0] as { agents: string }).agents).toContain("## Restrictions");
  });
});
