import { act, renderHook } from "@testing-library/react";
import { useHashPage } from "./useHashPage";

describe("useHashPage", () => {
  afterEach(() => {
    window.location.hash = "";
  });

  it("reads the page slug and query params from the hash", () => {
    window.location.hash = "#/mcp?tambah=1";
    const { result } = renderHook(() => useHashPage());
    expect(result.current[0]).toBe("mcp");
    expect(result.current[2]).toEqual({ tambah: "1" });
  });

  it("falls back to ringkasan for unknown slugs, dropping params", () => {
    window.location.hash = "#/tidak-ada?x=1";
    const { result } = renderHook(() => useHashPage());
    expect(result.current[0]).toBe("ringkasan");
    expect(result.current[2]).toEqual({});
  });

  it("writes page + params to the hash on setPage", () => {
    window.location.hash = "";
    const { result } = renderHook(() => useHashPage());
    act(() => result.current[1]("mcp", { tambah: "1" }));
    expect(window.location.hash).toBe("#/mcp?tambah=1");
    expect(result.current[0]).toBe("mcp");
    expect(result.current[2]).toEqual({ tambah: "1" });

    act(() => result.current[1]("skill"));
    expect(window.location.hash).toBe("#/skill");
    expect(result.current[2]).toEqual({});
  });

  it("follows external hashchange events", () => {
    window.location.hash = "#/mcp?tambah=1";
    const { result } = renderHook(() => useHashPage());
    act(() => {
      window.location.hash = "#/skill";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(result.current[0]).toBe("skill");
    expect(result.current[2]).toEqual({});
  });
});
