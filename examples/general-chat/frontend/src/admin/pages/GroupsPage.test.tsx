import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../Toast";
import { GroupsPage } from "./GroupsPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const GROUP = {
  id: "tim-keuangan",
  name: "Tim Keuangan",
  description: "Tim pelaporan keuangan",
  createdAt: "2026-08-18T00:00:00Z",
  createdBy: "admin@x.co",
  memberCount: 1,
};

const USERS = [
  {
    email: "budi@x.co",
    role: "user",
    displayName: "Budi",
    createdAt: null,
    addedBy: null,
    group: "tim-keuangan",
  },
];

describe("GroupsPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists groups from the API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/admin/groups") return jsonResponse({ groups: [GROUP] });
        if (url === "/admin/users") return jsonResponse({ users: USERS });
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <GroupsPage />
      </ToastProvider>,
    );
    expect(await screen.findByText("Tim Keuangan")).toBeDefined();
    expect(screen.getByText(/1 grup terdaftar/)).toBeDefined();
  });

  it("shows the full source manager (incl. upload) in the group detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/admin/groups") return jsonResponse({ groups: [GROUP] });
        if (url === "/admin/users") return jsonResponse({ users: USERS });
        if (url === "/admin/groups/tim-keuangan/sources") {
          return jsonResponse({
            sources: [{ id: "src-1", name: "sop-tim.pdf", kind: "document" }],
          });
        }
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    render(
      <ToastProvider>
        <GroupsPage />
      </ToastProvider>,
    );
    await userEvent.click(await screen.findByText("Kelola"));
    expect(await screen.findByText("sop-tim.pdf")).toBeDefined();
    expect(screen.getByText("Unggah Dokumen")).toBeDefined();
    expect(screen.getByText("Tempel Teks")).toBeDefined();
    expect(screen.getByText("Tambah URL")).toBeDefined();
  });
});
