import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("puts Buka Chat first in the sidebar", () => {
    render(
      <ToastProvider>
        <AdminShell me={ME} user={null} onSignOut={vi.fn()} />
      </ToastProvider>,
    );
    const nav = screen.getByRole("navigation", { name: "Navigasi admin" });
    const buttons = within(nav).getAllByRole("button");
    expect(buttons[0]).toHaveTextContent("Buka Chat");
    expect(buttons[1]).toHaveTextContent("Ringkasan");
  });

  it("can collapse the admin sidebar to icon-only mode", async () => {
    window.location.hash = "#chat";
    render(
      <ToastProvider>
        <AdminShell me={ME} user={null} onSignOut={vi.fn()} />
      </ToastProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Minimize menu panel" }));

    expect(screen.getByRole("complementary")).toHaveClass("admin-sidebar--collapsed");
    expect(screen.getByRole("button", { name: "Tampilkan menu panel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Buka Chat" })).toHaveAttribute(
      "title",
      "Buka Chat",
    );
  });
});
