import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../Toast";
import { AgentPickerPanel } from "./AgentPicker";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const AGENTS = [
  { id: "analis-keuangan", name: "Analis Keuangan", description: "Keuangan dan pajak." },
  { id: "peninjau-legal", name: "Peninjau Legal", description: "Kontrak dan regulasi." },
];

describe("AgentPickerPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows auto, agents, and default assistant options", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("/chat/agent-selection")) return jsonResponse({ agentId: "auto" });
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <AgentPickerPanel sessionId="sess-1" agents={AGENTS} />
      </ToastProvider>,
    );
    expect(await screen.findByText("Otomatis")).toBeDefined();
    expect(screen.getByText("Analis Keuangan")).toBeDefined();
    expect(screen.getByText("Peninjau Legal")).toBeDefined();
    expect(screen.getByText("Asisten bawaan")).toBeDefined();
  });

  it("loads the stored selection and saves a new one", async () => {
    const putBodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/chat/agent-selection" && init?.method === "PUT") {
          putBodies.push(JSON.parse(String(init.body)));
          return jsonResponse({ ok: true, agentId: "analis-keuangan" });
        }
        if (url.startsWith("/chat/agent-selection")) {
          return jsonResponse({ agentId: "peninjau-legal" });
        }
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <AgentPickerPanel sessionId="sess-1" agents={AGENTS} />
      </ToastProvider>,
    );
    await waitFor(() =>
      expect((screen.getByLabelText("Peninjau Legal") as HTMLInputElement).checked).toBe(true),
    );
    await userEvent.click(screen.getByLabelText("Analis Keuangan"));
    await waitFor(() => expect(putBodies).toHaveLength(1));
    expect(putBodies[0]).toEqual({ threadId: "sess-1", agentId: "analis-keuangan" });
  });

  it("disables options without an active session", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({})),
    );
    render(
      <ToastProvider>
        <AgentPickerPanel sessionId={null} agents={AGENTS} />
      </ToastProvider>,
    );
    expect(screen.getByText(/Mulai percakapan terlebih dahulu/)).toBeDefined();
    expect((screen.getByLabelText("Otomatis") as HTMLInputElement).disabled).toBe(true);
  });
});
