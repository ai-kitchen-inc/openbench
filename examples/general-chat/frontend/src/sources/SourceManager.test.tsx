import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../Toast";
import type { ManagedSource } from "./model";
import { SourceManager, type SourceManagerApi } from "./SourceManager";

function source(overrides: Partial<ManagedSource>): ManagedSource {
  return {
    id: "s1",
    name: "panduan.pdf",
    kind: "document",
    status: "ready",
    url: null,
    ...overrides,
  };
}

function renderManager(api: SourceManagerApi, props: Record<string, unknown> = {}) {
  return render(
    <ToastProvider>
      <SourceManager api={api} {...props} />
    </ToastProvider>,
  );
}

describe("SourceManager", () => {
  it("lists sources and shows failure details", async () => {
    const api: SourceManagerApi = {
      list: vi.fn().mockResolvedValue([
        source({}),
        source({ id: "s2", name: "rusak.pdf", status: "failed", error: "Parser gagal" }),
      ]),
      remove: vi.fn(),
    };
    renderManager(api);
    expect(await screen.findByText("panduan.pdf")).toBeInTheDocument();
    expect(screen.getByText("Parser gagal")).toBeInTheDocument();
    // No handlers provided — no add buttons.
    expect(screen.queryByText("Unggah Dokumen")).toBeNull();
    expect(screen.queryByText("Tempel Teks")).toBeNull();
    expect(screen.queryByText("Tambah URL")).toBeNull();
  });

  it("adds a text source and refreshes the list", async () => {
    const addText = vi.fn().mockResolvedValue(source({ id: "s3", name: "FAQ", kind: "text" }));
    const list = vi
      .fn()
      .mockResolvedValueOnce([])
      .mockResolvedValue([source({ id: "s3", name: "FAQ", kind: "text" })]);
    const api: SourceManagerApi = { list, addText, remove: vi.fn() };
    renderManager(api);
    await screen.findByText("Belum ada sumber.");

    await userEvent.click(screen.getByText("Tempel Teks"));
    await userEvent.type(
      screen.getByPlaceholderText("Nama sumber (mis. FAQ Layanan Publik)"),
      "FAQ",
    );
    await userEvent.type(
      screen.getByPlaceholderText("Tempel teks sumber yang dapat ditanyakan pengguna..."),
      "Isi FAQ",
    );
    await userEvent.click(screen.getByText("Tambah Sumber Teks"));

    await waitFor(() => expect(addText).toHaveBeenCalledWith("FAQ", "Isi FAQ"));
    expect(await screen.findByText("FAQ")).toBeInTheDocument();
  });

  it("removes a source through the adapter", async () => {
    const remove = vi.fn().mockResolvedValue(undefined);
    const list = vi
      .fn()
      .mockResolvedValueOnce([source({})])
      .mockResolvedValue([]);
    renderManager({ list, remove });
    await screen.findByText("panduan.pdf");
    await userEvent.click(screen.getByLabelText("Hapus panduan.pdf"));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("s1"));
  });

  it("shows the disabled hint instead of loading when disabled", async () => {
    const list = vi.fn();
    renderManager(
      { list, remove: vi.fn(), addUrl: vi.fn() },
      { disabled: true, disabledHint: "Mulai percakapan untuk menambah sumber." },
    );
    expect(
      await screen.findByText("Mulai percakapan untuk menambah sumber."),
    ).toBeInTheDocument();
    expect(list).not.toHaveBeenCalled();
    expect(screen.getByText("Tambah URL")).toBeDisabled();
  });
});
