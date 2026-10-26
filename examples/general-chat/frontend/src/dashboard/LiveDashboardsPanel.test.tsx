import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../Toast";
import {
  LiveDashboardsPanel,
  editDashboardPrompt,
  formatInterval,
  openDashboardPrompt,
} from "./LiveDashboardsPanel";

const chat = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  createSession: vi.fn(),
  isStreaming: false,
  activeSessionId: "session-1" as string | null,
}));

vi.mock("@openbench/chat-ui", () => ({
  useChatContext: () => chat,
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ITEMS = [
  {
    id: "abcdef123456",
    title: "Penjualan Live",
    description: "",
    refreshIntervalSeconds: 30,
    enabled: true,
    public: false,
    version: 3,
    lastRefreshAt: "2026-10-19T08:00:00+00:00",
    lastError: null,
    nextRunAt: null,
    createdAt: "",
    updatedAt: "",
    rowCounts: { by_region: 4 },
  },
  {
    id: "0123456789ab",
    title: "Rusak",
    description: "",
    refreshIntervalSeconds: 0,
    enabled: false,
    public: true,
    version: 1,
    lastRefreshAt: null,
    lastError: "total: relation x does not exist",
    nextRunAt: null,
    createdAt: "",
    updatedAt: "",
    rowCounts: {},
  },
];

function stubFetch() {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url === "/dashboard/live" && method === "GET") return jsonResponse({ dashboards: ITEMS });
      if (method === "PATCH") {
        const id = url.split("/").pop();
        const item = ITEMS.find((entry) => entry.id === id);
        return jsonResponse({ ...item, ...body });
      }
      if (url.endsWith("/refresh")) return jsonResponse({ id: "abcdef123456", version: 4 });
      if (method === "DELETE") return jsonResponse({ ok: true });
      return jsonResponse({});
    }),
  );
  return calls;
}

function renderPanel(onRequestClose = vi.fn()) {
  render(
    <ToastProvider>
      <LiveDashboardsPanel onRequestClose={onRequestClose} />
    </ToastProvider>,
  );
  return onRequestClose;
}

describe("LiveDashboardsPanel", () => {
  beforeEach(() => {
    chat.sendMessage.mockClear();
    chat.createSession.mockClear();
    chat.isStreaming = false;
    chat.activeSessionId = "session-1";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("lists dashboards with status pills and the public link", async () => {
    stubFetch();
    renderPanel();
    expect(await screen.findByText("Penjualan Live")).toBeInTheDocument();
    expect(screen.getByText("aktif")).toBeInTheDocument();
    const broken = screen.getByText("error");
    expect(broken).toHaveAttribute("title", "total: relation x does not exist");
    expect(screen.getByText(/manual/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /\/d\/0123456789ab$/ })).toBeInTheDocument();
  });

  it("opens a dashboard through the chat and closes the dialog", async () => {
    stubFetch();
    const onRequestClose = renderPanel();
    await screen.findByText("Penjualan Live");
    const row = screen.getByText("Penjualan Live").closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Buka" }));
    expect(chat.sendMessage).toHaveBeenCalledWith(
      'Buka dashboard live `abcdef123456` ("Penjualan Live")',
    );
    expect(onRequestClose).toHaveBeenCalled();
    expect(chat.createSession).not.toHaveBeenCalled();
  });

  it("sends an edit instruction to the agent", async () => {
    stubFetch();
    chat.activeSessionId = null;
    const onRequestClose = renderPanel();
    await screen.findByText("Penjualan Live");
    const row = screen.getByText("Penjualan Live").closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Ubah dengan prompt" }));
    const submit = within(row).getByRole("button", { name: "Kirim ke asisten" });
    expect(submit).toBeDisabled();
    await userEvent.type(within(row).getByRole("textbox"), "tambahkan grafik per bulan");
    await userEvent.click(submit);
    expect(chat.createSession).toHaveBeenCalled();
    expect(chat.sendMessage).toHaveBeenCalledWith(
      'Perbarui dashboard live `abcdef123456` ("Penjualan Live"): tambahkan grafik per bulan',
    );
    expect(onRequestClose).toHaveBeenCalled();
  });

  it("disables chat hand-offs while the assistant is streaming", async () => {
    stubFetch();
    chat.isStreaming = true;
    renderPanel();
    await screen.findByText("Penjualan Live");
    const row = screen.getByText("Penjualan Live").closest("li") as HTMLElement;
    expect(within(row).getByRole("button", { name: "Buka" })).toBeDisabled();
  });

  it("toggles public and pause through PATCH", async () => {
    const calls = stubFetch();
    renderPanel();
    await screen.findByText("Penjualan Live");
    const row = screen.getByText("Penjualan Live").closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Publikasikan" }));
    await waitFor(() =>
      expect(within(row).getByRole("link", { name: /\/d\/abcdef123456$/ })).toBeInTheDocument(),
    );
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ public: true });
    await userEvent.click(within(row).getByRole("button", { name: "Jeda" }));
    await waitFor(() => expect(within(row).getByText("jeda")).toBeInTheDocument());
    const patches = calls.filter((call) => call.method === "PATCH");
    expect(patches[patches.length - 1]?.body).toEqual({ enabled: false });
  });

  it("deletes after confirmation", async () => {
    const calls = stubFetch();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel();
    await screen.findByText("Penjualan Live");
    const row = screen.getByText("Penjualan Live").closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Hapus" }));
    await waitFor(() => expect(screen.queryByText("Penjualan Live")).not.toBeInTheDocument());
    expect(calls.some((call) => call.method === "DELETE" && call.url.endsWith("/abcdef123456"))).toBe(
      true,
    );
  });

  it("formats prompts and intervals", () => {
    expect(openDashboardPrompt({ id: "x", title: "T" })).toBe('Buka dashboard live `x` ("T")');
    expect(editDashboardPrompt({ id: "x", title: "T" }, "  ubah  ")).toBe(
      'Perbarui dashboard live `x` ("T"): ubah',
    );
    expect(formatInterval(0)).toBe("manual");
    expect(formatInterval(45)).toBe("45 dtk");
    expect(formatInterval(300)).toBe("5 mnt");
    expect(formatInterval(7200)).toBe("2 jam");
  });
});
