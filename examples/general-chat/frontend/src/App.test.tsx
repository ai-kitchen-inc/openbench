import { render, screen } from "@testing-library/react";
import App from "./App";

// ── Firebase mocks: the gate only needs a signed-in user and a token. ──

const fakeUser = {
  uid: "user-1",
  email: "orang@instansi.go.id",
  displayName: "Orang Uji",
  getIdToken: async () => "test-token",
};

vi.mock("./firebase", () => ({
  isFirebaseConfigured: () => true,
  getFirebaseAuth: () => ({}),
  googleProvider: {},
}));

vi.mock("firebase/auth", () => ({
  onAuthStateChanged: (
    _auth: unknown,
    next: (user: unknown) => void,
  ) => {
    next(fakeUser);
    return () => {};
  },
  signInWithPopup: vi.fn(),
  signOut: vi.fn(),
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function meResponse(role: "admin" | "user") {
  const all = role === "admin";
  return {
    email: fakeUser.email,
    role,
    displayName: fakeUser.displayName,
    group: "",
    capabilities: {
      attachments: all,
      session_sources: all,
      mcp_management: all,
      custom_functions: all,
      dashboards: all,
      image_search: all,
    },
    global: { file_generation: true },
  };
}

function stubFetch(role: "admin" | "user") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/account/me")) return jsonResponse(meResponse(role));
      if (url.startsWith("/account/shared-sources")) {
        return jsonResponse({ sources: [], groupSources: [] });
      }
      if (url.startsWith("/admin/shared-sources")) return jsonResponse({ sources: [] });
      if (url.startsWith("/admin/users")) return jsonResponse({ users: [] });
      if (url.startsWith("/admin/groups")) return jsonResponse({ groups: [] });
      if (url.startsWith("/admin/capabilities")) {
        return jsonResponse({ definitions: [], roles: { user: {} }, global: {} });
      }
      if (url.startsWith("/mcp/catalogs")) return jsonResponse({ servers: [] });
      if (url.startsWith("/sessions")) return jsonResponse([]);
      if (url.startsWith("/persona")) return jsonResponse({ loaded: false });
      if (url.startsWith("/skills")) return jsonResponse({ loaded: false, skills: [] });
      if (url.startsWith("/chat/sources/")) return jsonResponse([]);
      return jsonResponse({});
    }),
  );
}

describe("App role branching", () => {
  beforeEach(() => {
    window.location.hash = "";
    window.localStorage.setItem("sss-theme", "light");
    // jsdom lacks these browser APIs used by the theme hook / chat surface.
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
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
  });

  it("renders the admin control panel for role=admin", async () => {
    stubFetch("admin");

    render(<App />);

    expect(await screen.findByText("Panel Kendali")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Buka Chat/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Kemampuan/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Skill Kustom/ })).toBeInTheDocument();
    expect(screen.getByText("Administrator")).toBeInTheDocument();
  });

  it("renders the user chat (no admin nav) for role=user", async () => {
    stubFetch("user");

    render(<App />);

    expect(await screen.findByTitle(fakeUser.email)).toBeInTheDocument();
    expect(screen.queryByText("Panel Kendali")).not.toBeInTheDocument();
    // Global sources drawer trigger is available to every user.
    expect(screen.getByRole("button", { name: /Sumber/ })).toBeInTheDocument();
  });
});
