import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../Toast";
import { CapabilitiesPage } from "./CapabilitiesPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const DEFINITIONS = [
  {
    id: "attachments",
    kind: "route",
    label: "Lampiran Percakapan",
    description: "Izinkan pengguna mengunggah lampiran di composer.",
    default: true,
  },
  {
    id: "file_generation",
    kind: "global",
    label: "Pembuatan Berkas",
    description: "Aktifkan pembuatan berkas untuk seluruh deployment.",
    default: true,
  },
];

describe("CapabilitiesPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders toggles from GET and PUTs a partial patch on toggle", async () => {
    const putBodies: unknown[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/admin/groups") return jsonResponse({ groups: [] });
      if (url === "/admin/capabilities" && (!init || !init.method)) {
        return jsonResponse({
          definitions: DEFINITIONS,
          roles: { user: { attachments: false } },
          global: { file_generation: true },
        });
      }
      if (url === "/admin/capabilities" && init?.method === "PUT") {
        putBodies.push(JSON.parse(String(init.body)));
        return jsonResponse({
          definitions: DEFINITIONS,
          roles: { user: { attachments: true } },
          global: { file_generation: true },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ToastProvider durationMs={0}>
        <CapabilitiesPage />
      </ToastProvider>,
    );

    // Grouped rendering: route flag under "Fitur Pengguna", global under "Global".
    expect(await screen.findByText("Fitur Pengguna")).toBeInTheDocument();
    expect(screen.getByText("Global")).toBeInTheDocument();

    const attachmentsSwitch = screen.getByRole("switch", { name: "Lampiran Percakapan" });
    expect(attachmentsSwitch).toHaveAttribute("aria-checked", "false");
    const globalSwitch = screen.getByRole("switch", { name: "Pembuatan Berkas" });
    expect(globalSwitch).toHaveAttribute("aria-checked", "true");

    await userEvent.click(attachmentsSwitch);

    expect(putBodies).toEqual([{ roles: { user: { attachments: true } } }]);
    expect(
      await screen.findByRole("switch", { name: "Lampiran Percakapan" }),
    ).toHaveAttribute("aria-checked", "true");
  });

  it("keeps state and shows an error toast when PUT fails", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/admin/groups") return jsonResponse({ groups: [] });
      if (url === "/admin/capabilities" && (!init || !init.method)) {
        return jsonResponse({
          definitions: DEFINITIONS,
          roles: { user: { attachments: false } },
          global: { file_generation: true },
        });
      }
      if (url === "/admin/capabilities" && init?.method === "PUT") {
        return jsonResponse({ detail: "Gagal memuat ulang agen." }, 500);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ToastProvider durationMs={0}>
        <CapabilitiesPage />
      </ToastProvider>,
    );

    const globalSwitch = await screen.findByRole("switch", { name: "Pembuatan Berkas" });
    await userEvent.click(globalSwitch);

    expect(
      await screen.findByText(/Gagal memperbarui Pembuatan Berkas: Gagal memuat ulang agen\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Pembuatan Berkas" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });
});
