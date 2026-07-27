/**
 * Tests for the export shortcuts rendered under ObTable.
 *
 * Clicking one sends an ordinary user turn asking for the file, so the
 * agent's export tools do the work — a deterministic path that does not
 * depend on the model noticing an export request in prose.
 */

import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ObTable } from "../src/a2ui/custom/ob-table";
import type { A2UIComponent, A2UISurface, TableExportConfig } from "../src/types";

const sendMessage = vi.fn();
let tableExport: TableExportConfig | undefined;
let isStreaming = false;
let hasProvider = true;

vi.mock("../src/components/ChatProvider", () => ({
  useChatContextOptional: () =>
    hasProvider ? { sendMessage, tableExport, isStreaming } : null,
}));

const surface: A2UISurface = {
  id: "surface-1",
  components: {},
  root: "root",
  dataModel: {},
} as unknown as A2UISurface;

const component = {
  id: "table-1",
  componentType: "ObTable",
  headers: ["Region", "Total"],
  rows: [["North", 10]],
} as unknown as A2UIComponent;

function renderTable() {
  return render(<ObTable component={component} surface={surface} />);
}

beforeEach(() => {
  sendMessage.mockClear();
  tableExport = undefined;
  isStreaming = false;
  hasProvider = true;
});

describe("ObTable export shortcuts", () => {
  it("renders Excel, PDF and Markdown by default", () => {
    renderTable();
    expect(screen.getByRole("button", { name: "Excel" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "PDF" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Markdown" })).toBeTruthy();
  });

  it("sends a user turn naming the requested format", async () => {
    renderTable();
    await userEvent.click(screen.getByRole("button", { name: "Excel" }));
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage.mock.calls[0][0]).toMatch(/\.xlsx/);
  });

  it("uses host-supplied labels and prompts", async () => {
    tableExport = {
      label: "Ekspor:",
      formats: [{ id: "xlsx", label: "Excel", prompt: "Ekspor tabel ke file Excel." }],
    };
    renderTable();
    expect(screen.getByText("Ekspor:")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "PDF" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Excel" }));
    expect(sendMessage).toHaveBeenCalledWith("Ekspor tabel ke file Excel.");
  });

  it("can be disabled by the host", () => {
    tableExport = { enabled: false };
    renderTable();
    expect(screen.queryByRole("button", { name: "Excel" })).toBeNull();
  });

  it("disables the buttons while a response streams", () => {
    isStreaming = true;
    renderTable();
    const button = screen.getByRole("button", { name: "Excel" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("renders nothing outside a ChatProvider", () => {
    hasProvider = false;
    renderTable();
    expect(screen.queryByRole("button", { name: "Excel" })).toBeNull();
    // The table itself still renders.
    expect(screen.getByText("Region")).toBeTruthy();
  });
});
