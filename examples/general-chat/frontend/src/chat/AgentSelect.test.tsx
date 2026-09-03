import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../Toast";
import { AgentSelect } from "./AgentSelect";

vi.mock("@openbench/chat-ui", () => ({
  useChatContext: () => ({ activeSessionId: "session-1" }),
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const AGENTS = {
  agents: [
    { id: "analis-keuangan", name: "Analis Keuangan", description: "Keuangan & pajak." },
  ],
  defaultMode: "auto",
};

describe("AgentSelect", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the current selection and saves a new one", async () => {
    const puts: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/chat/agents") return jsonResponse(AGENTS);
        if (url.startsWith("/chat/agent-selection") && init?.method === "PUT") {
          puts.push(JSON.parse(String(init.body)));
          return jsonResponse({ ok: true, agentId: "analis-keuangan" });
        }
        if (url.startsWith("/chat/agent-selection")) {
          return jsonResponse({ agentId: "auto" });
        }
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <AgentSelect />
      </ToastProvider>,
    );
    const trigger = await screen.findByLabelText("Pilih agen");
    expect(trigger.textContent).toContain("Otomatis");

    await userEvent.click(trigger);
    await userEvent.click(screen.getByText("Analis Keuangan"));
    await waitFor(() =>
      expect(puts).toEqual([{ threadId: "session-1", agentId: "analis-keuangan" }]),
    );
    expect(trigger.textContent).toContain("Analis Keuangan");
  });

  it("renders nothing when there are no agents", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/chat/agents") return jsonResponse({ agents: [], defaultMode: "default" });
        if (url.startsWith("/chat/agent-selection")) return jsonResponse({ agentId: "" });
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    const { container } = render(
      <ToastProvider>
        <AgentSelect />
      </ToastProvider>,
    );
    await waitFor(() => expect(container.querySelector(".agent-select")).toBeNull());
  });

  it("renders nothing when disabled by capability", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(
      <ToastProvider>
        <AgentSelect enabled={false} />
      </ToastProvider>,
    );
    expect(container.querySelector(".agent-select")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalledWith("/chat/agents");
  });
});
