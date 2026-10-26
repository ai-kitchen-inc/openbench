import { describe, expect, it } from "vitest";
import { formatSourceMeta, sourceKindLabel, type ManagedSource } from "./model";

function source(overrides: Partial<ManagedSource>): ManagedSource {
  return { id: "s1", name: "laporan.pdf", kind: "document", ...overrides };
}

describe("sourceKindLabel", () => {
  it("maps known kinds to Indonesian badge labels", () => {
    expect(sourceKindLabel(source({ kind: "url" }))).toBe("WEB");
    expect(sourceKindLabel(source({ kind: "text" }))).toBe("TEKS");
    expect(sourceKindLabel(source({ kind: "image" }))).toBe("GAMBAR");
    expect(sourceKindLabel(source({ kind: "document" }))).toBe("DOCUMENT");
  });

  it("splits spreadsheets by extension", () => {
    expect(sourceKindLabel(source({ kind: "spreadsheet", name: "data.CSV" }))).toBe("CSV");
    expect(sourceKindLabel(source({ kind: "spreadsheet", name: "data.xlsx" }))).toBe("XLSX");
  });

  it("falls back when kind is missing", () => {
    expect(sourceKindLabel(source({ kind: undefined }))).toBe("SUMBER");
  });
});

describe("formatSourceMeta", () => {
  it("reports processing state with optional parse status", () => {
    expect(formatSourceMeta(source({ status: "processing" }))).toBe("Memproses sumber");
    expect(
      formatSourceMeta(source({ status: "processing", metadata: { parseStatus: "OCR" } })),
    ).toBe("Memproses: OCR");
  });

  it("describes images from metadata", () => {
    expect(formatSourceMeta(source({ kind: "image", status: "ready" }))).toBe(
      "OCR gambar siap",
    );
    expect(
      formatSourceMeta(
        source({ kind: "image", status: "ready", metadata: { description: "Struk belanja" } }),
      ),
    ).toBe("Struk belanja");
  });

  it("falls back to the URL, then null", () => {
    expect(formatSourceMeta(source({ status: "ready", url: "https://a.example" }))).toBe(
      "https://a.example",
    );
    expect(formatSourceMeta(source({ status: "ready" }))).toBeNull();
  });
});
