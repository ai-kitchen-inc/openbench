import { render, screen, within } from "@testing-library/react";
import { ToastProvider } from "../Toast";
import type { Me } from "../account/api";
import { AdminShell } from "./AdminShell";

vi.mock("../chat/UserChat", () => ({
  UserChat: () => <div>chat-stub</div>,
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ME: Me = {
  email: "admin@instansi.go.id",
  role: "admin",
  displayName: "Admin Uji",
  group: "",
  capabilities: {
    attachments: true,
    session_sources: true,
    mcp_management: true,
    custom_functions: true,
    dashboards: true,
    image_search: true,
  },
  global: { file_generation: true },
};

describe("AdminShell navigation", () => {
  beforeEach(() => {
    window.location.hash = "";
    window.localStorage.setItem("sss-theme", "light");
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({})),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps Ringkasan first and Buka Chat last in the sidebar", () => {
    render(
      <ToastProvider>
        <AdminShell me={ME} user={null} onSignOut={vi.fn()} />
      </ToastProvider>,
    );
    const nav = screen.getByRole("navigation", { name: "Navigasi admin" });
    const buttons = within(nav).getAllByRole("button");
    expect(buttons[0]).toHaveTextContent("Ringkasan");
    expect(buttons[buttons.length - 1]).toHaveTextContent("Buka Chat");
  });
});
