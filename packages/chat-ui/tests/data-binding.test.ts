/**
 * Tests for A2UI data binding resolver.
 */

import { describe, expect, it, vi } from "vitest";
import {
  resolveBoolean,
  resolveNumber,
  resolvePointer,
  resolveString,
  resolveValue,
} from "../src/a2ui/data-binding";
import type { A2UISurface } from "../src/types";

/** Helper to create a minimal surface with a data model. */
function makeSurface(dataModel: Record<string, unknown>): A2UISurface {
  return {
    surfaceId: "test",
    catalogId: "test",
    components: new Map(),
    dataModel,
  };
}

// ── resolvePointer ──

describe("resolvePointer", () => {
  it('returns entire object for root path "/"', () => {
    const obj = { a: 1, b: 2 };
    expect(resolvePointer(obj, "/")).toBe(obj);
  });

  it('returns entire object for empty path ""', () => {
    const obj = { a: 1 };
    expect(resolvePointer(obj, "")).toBe(obj);
  });

  it("resolves top-level key", () => {
    expect(resolvePointer({ name: "Alice" }, "/name")).toBe("Alice");
  });

  it("resolves nested path", () => {
    const obj = { user: { address: { city: "NYC" } } };
    expect(resolvePointer(obj, "/user/address/city")).toBe("NYC");
  });

  it("resolves array index", () => {
    const obj = { items: ["a", "b", "c"] };
    expect(resolvePointer(obj, "/items/1")).toBe("b");
  });

  it("returns undefined for missing path", () => {
    expect(resolvePointer({ a: 1 }, "/b")).toBeUndefined();
  });

  it("returns undefined for deep missing path", () => {
    expect(resolvePointer({ a: { b: 1 } }, "/a/c/d")).toBeUndefined();
  });

  it("handles ~0 escape (tilde)", () => {
    const obj = { "a~b": "tilde" };
    expect(resolvePointer(obj, "/a~0b")).toBe("tilde");
  });

  it("handles ~1 escape (slash)", () => {
    const obj = { "a/b": "slash" };
    expect(resolvePointer(obj, "/a~1b")).toBe("slash");
  });
});

// ── resolveValue ──

describe("resolveValue", () => {
  it("passes through static string", () => {
    const surface = makeSurface({});
    expect(resolveValue("hello", surface)).toBe("hello");
  });

  it("passes through static number", () => {
    const surface = makeSurface({});
    expect(resolveValue(42, surface)).toBe(42);
  });

  it("passes through static boolean", () => {
    const surface = makeSurface({});
    expect(resolveValue(true, surface)).toBe(true);
  });

  it("resolves DataBinding", () => {
    const surface = makeSurface({ user: { name: "Bob" } });
    expect(resolveValue({ path: "/user/name" }, surface)).toBe("Bob");
  });

  it("resolves FunctionCall — formatString", () => {
    const surface = makeSurface({});
    const result = resolveValue(
      {
        call: "formatString",
        args: { template: "Hello {name}!", values: { name: "Alice" } },
      },
      surface,
    );
    expect(result).toBe("Hello Alice!");
  });

  it("resolves FunctionCall with DataBinding in args", () => {
    const surface = makeSurface({ user: { name: "Charlie" } });
    const result = resolveValue(
      {
        call: "formatString",
        args: {
          template: "Hi {name}!",
          values: { name: { path: "/user/name" } },
        },
      },
      surface,
    );
    expect(result).toBe("Hi Charlie!");
  });
});

// ── Coercion helpers ──

describe("resolveString", () => {
  it("converts number to string", () => {
    const surface = makeSurface({});
    expect(resolveString(42, surface)).toBe("42");
  });

  it("returns empty string for null", () => {
    const surface = makeSurface({});
    expect(resolveString(null, surface)).toBe("");
  });

  it("returns empty string for undefined", () => {
    const surface = makeSurface({});
    expect(resolveString(undefined, surface)).toBe("");
  });
});

describe("resolveNumber", () => {
  it("returns number as-is", () => {
    const surface = makeSurface({});
    expect(resolveNumber(42, surface)).toBe(42);
  });

  it("converts string to number", () => {
    const surface = makeSurface({});
    expect(resolveNumber("3.14", surface)).toBe(3.14);
  });

  it("returns 0 for non-numeric", () => {
    const surface = makeSurface({});
    expect(resolveNumber("abc", surface)).toBe(0);
  });
});

describe("resolveBoolean", () => {
  it("returns boolean as-is", () => {
    const surface = makeSurface({});
    expect(resolveBoolean(true, surface)).toBe(true);
  });

  it("truthy string is true", () => {
    const surface = makeSurface({});
    expect(resolveBoolean("yes", surface)).toBe(true);
  });

  it("empty string is false", () => {
    const surface = makeSurface({});
    expect(resolveBoolean("", surface)).toBe(false);
  });
});

// ── Built-in functions ──

describe("built-in functions", () => {
  const surface = makeSurface({});

  describe("required", () => {
    it("returns true for non-empty value", () => {
      expect(resolveValue({ call: "required", args: { value: "hi" } }, surface)).toBe(true);
    });
    it("returns false for empty string", () => {
      expect(resolveValue({ call: "required", args: { value: "" } }, surface)).toBe(false);
    });
    it("returns false for null", () => {
      expect(resolveValue({ call: "required", args: { value: null } }, surface)).toBe(false);
    });
  });

  describe("email", () => {
    it("validates correct email", () => {
      expect(resolveValue({ call: "email", args: { value: "a@b.com" } }, surface)).toBe(true);
    });
    it("rejects invalid email", () => {
      expect(resolveValue({ call: "email", args: { value: "not-email" } }, surface)).toBe(false);
    });
  });

  describe("numeric", () => {
    it("validates number", () => {
      expect(resolveValue({ call: "numeric", args: { value: 42 } }, surface)).toBe(true);
    });
    it("validates numeric string", () => {
      expect(resolveValue({ call: "numeric", args: { value: "3.14" } }, surface)).toBe(true);
    });
    it("rejects non-numeric", () => {
      expect(resolveValue({ call: "numeric", args: { value: "abc" } }, surface)).toBe(false);
    });
  });

  describe("regex", () => {
    it("matches pattern", () => {
      expect(
        resolveValue(
          { call: "regex", args: { value: "abc123", pattern: "^[a-z]+\\d+$" } },
          surface,
        ),
      ).toBe(true);
    });
    it("rejects non-match", () => {
      expect(
        resolveValue({ call: "regex", args: { value: "!!!", pattern: "^[a-z]+$" } }, surface),
      ).toBe(false);
    });
  });

  describe("length", () => {
    it("validates within range", () => {
      expect(
        resolveValue({ call: "length", args: { value: "hello", min: 1, max: 10 } }, surface),
      ).toBe(true);
    });
    it("rejects too short", () => {
      expect(resolveValue({ call: "length", args: { value: "", min: 1, max: 10 } }, surface)).toBe(
        false,
      );
    });
  });

  describe("formatCurrency", () => {
    it("formats USD", () => {
      const result = resolveValue(
        { call: "formatCurrency", args: { value: 1234.5, currency: "USD" } },
        surface,
      );
      expect(result).toContain("1,234.50");
    });
  });

  describe("pluralize", () => {
    it("singular for count 1", () => {
      expect(
        resolveValue({ call: "pluralize", args: { count: 1, singular: "item" } }, surface),
      ).toBe("item");
    });
    it("plural for count > 1", () => {
      expect(
        resolveValue({ call: "pluralize", args: { count: 5, singular: "item" } }, surface),
      ).toBe("items");
    });
    it("custom plural", () => {
      expect(
        resolveValue(
          { call: "pluralize", args: { count: 3, singular: "child", plural: "children" } },
          surface,
        ),
      ).toBe("children");
    });
  });

  describe("logic functions", () => {
    it("and — all true", () => {
      expect(resolveValue({ call: "and", args: { conditions: [true, true, true] } }, surface)).toBe(
        true,
      );
    });
    it("and — one false", () => {
      expect(
        resolveValue({ call: "and", args: { conditions: [true, false, true] } }, surface),
      ).toBe(false);
    });
    it("or — one true", () => {
      expect(
        resolveValue({ call: "or", args: { conditions: [false, true, false] } }, surface),
      ).toBe(true);
    });
    it("not — inverts", () => {
      expect(resolveValue({ call: "not", args: { value: false } }, surface)).toBe(true);
    });
  });

  describe("unknown function", () => {
    it("returns undefined and warns", () => {
      const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
      expect(resolveValue({ call: "nonexistent", args: {} }, surface)).toBeUndefined();
      expect(warn).toHaveBeenCalledWith(expect.stringContaining("nonexistent"));
      warn.mockRestore();
    });
  });
});
