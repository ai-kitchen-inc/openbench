import { render, screen, waitFor } from "@testing-library/react";
import { ToastProvider } from "../Toast";
import { EmbedChat } from "./EmbedChat";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(agentStatus = 200) {
  const calls: { url: string; auth: string | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, auth: new Headers(init?.headers).get("Authorization") });
      if (url === "/agents/analis-keuangan") {
        return agentStatus === 200
          ? jsonResponse({
              id: "analis-keuangan",
              name: "Analis Keuangan",
              description: "Laporan keuangan.",
            })
          : jsonResponse({ detail: "no" }, agentStatus);
      }
      if (url.startsWith("/agents/analis-keuangan/sessions")) {
        return jsonResponse({ detail: "Riwayat sesi tidak tersedia." }, 501);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }),
  );
  return calls;
}

describe("EmbedChat", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    );
    Element.prototype.scrollIntoView = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.classList.remove("embed-root");
  });

  it("loads the agent card with the embed key and renders the chat panel", async () => {
    const calls = stubFetch();
    render(
      <ToastProvider>
        <EmbedChat agentId="analis-keuangan" embedKey="k-123" theme="dark" />
      </ToastProvider>,
    );
    expect(await screen.findByText("Analis Keuangan")).toBeInTheDocument();
    expect(calls[0]).toEqual({ url: "/agents/analis-keuangan", auth: "Bearer k-123" });
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.body.classList.contains("embed-root")).toBe(true);
    // The SDK's session hydration goes to the per-agent 501 endpoint with the key.
    await waitFor(() =>
      expect(calls.some((call) => call.url.startsWith("/agents/analis-keuangan/sessions"))).toBe(
        true,
      ),
    );
    expect(
      calls.find((call) => call.url.startsWith("/agents/analis-keuangan/sessions"))?.auth,
    ).toBe("Bearer k-123");
  });

  it("rejects a missing key without touching the network", () => {
    const calls = stubFetch();
    render(
      <ToastProvider>
        <EmbedChat agentId="analis-keuangan" embedKey="" theme={null} />
      </ToastProvider>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Kunci embed tidak valid.");
    expect(calls).toHaveLength(0);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("shows an error when the backend rejects the key", async () => {
    stubFetch(401);
    render(
      <ToastProvider>
        <EmbedChat agentId="analis-keuangan" embedKey="wrong" theme={null} />
      </ToastProvider>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Kunci embed tidak valid atau agen tidak tersedia.",
    );
  });
});
