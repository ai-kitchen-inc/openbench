/**
 * Tests for A2UIMessageProcessor.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { A2UIMessageProcessor } from "../src/core/message-processor";

describe("A2UIMessageProcessor", () => {
  let processor: A2UIMessageProcessor;

  beforeEach(() => {
    processor = new A2UIMessageProcessor();
  });

  // ── createSurface ──

  describe("createSurface", () => {
    it("creates a surface from a valid message", () => {
      processor.processMessage({
        version: "v0.10",
        createSurface: {
          surfaceId: "s1",
          catalogId: "test-catalog",
        },
      });

      const surface = processor.getSurface("s1");
      expect(surface).toBeDefined();
      expect(surface?.surfaceId).toBe("s1");
      expect(surface?.catalogId).toBe("test-catalog");
      expect(surface?.components).toBeInstanceOf(Map);
      expect(surface?.components.size).toBe(0);
      expect(surface?.dataModel).toEqual({});
    });

    it("sets theme on surface", () => {
      processor.processMessage({
        version: "v0.10",
        createSurface: {
          surfaceId: "s1",
          catalogId: "cat",
          theme: { primaryColor: "#FF0000", agentDisplayName: "Bot" },
        },
      });

      const surface = processor.getSurface("s1");
      expect(surface?.theme).toEqual({
        primaryColor: "#FF0000",
        agentDisplayName: "Bot",
      });
    });

    it("sets sendDataModel flag", () => {
      processor.processMessage({
        version: "v0.10",
        createSurface: {
          surfaceId: "s1",
          catalogId: "cat",
          sendDataModel: true,
        },
      });

      expect(processor.getSurface("s1")?.sendDataModel).toBe(true);
    });

    it("notifies listeners on create", () => {
      const listener = vi.fn();
      processor.onChange(listener);

      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s1", catalogId: "cat" },
      });

      expect(listener).toHaveBeenCalledWith("s1");
      expect(listener).toHaveBeenCalledTimes(1);
    });
  });

  // ── updateComponents ──

  describe("updateComponents", () => {
    beforeEach(() => {
      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s1", catalogId: "cat" },
      });
    });

    it("adds components to a surface", () => {
      processor.processMessage({
        version: "v0.10",
        updateComponents: {
          surfaceId: "s1",
          components: [
            { id: "root", component: "Column" },
            { id: "text1", component: "Text", text: "Hello" },
          ],
        },
      });

      const surface = processor.getSurface("s1")!;
      expect(surface.components.size).toBe(2);
      expect(surface.components.get("root")).toEqual({
        id: "root",
        component: "Column",
      });
      expect(surface.components.get("text1")).toEqual({
        id: "text1",
        component: "Text",
        text: "Hello",
      });
    });

    it("replaces existing component by ID", () => {
      processor.processMessage({
        version: "v0.10",
        updateComponents: {
          surfaceId: "s1",
          components: [{ id: "text1", component: "Text", text: "Old" }],
        },
      });

      processor.processMessage({
        version: "v0.10",
        updateComponents: {
          surfaceId: "s1",
          components: [{ id: "text1", component: "Text", text: "New" }],
        },
      });

      const comp = processor.getSurface("s1")?.components.get("text1");
      expect(comp).toEqual({ id: "text1", component: "Text", text: "New" });
    });

    it("warns for unknown surface", () => {
      const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

      processor.processMessage({
        version: "v0.10",
        updateComponents: {
          surfaceId: "unknown",
          components: [{ id: "c1", component: "Text" }],
        },
      });

      expect(warn).toHaveBeenCalledWith(expect.stringContaining("unknown surface"));
      warn.mockRestore();
    });

    it("notifies listeners on update", () => {
      const listener = vi.fn();
      processor.onChange(listener);

      processor.processMessage({
        version: "v0.10",
        updateComponents: {
          surfaceId: "s1",
          components: [{ id: "root", component: "Column" }],
        },
      });

      expect(listener).toHaveBeenCalledWith("s1");
    });
  });

  // ── updateDataModel ──

  describe("updateDataModel", () => {
    beforeEach(() => {
      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s1", catalogId: "cat" },
      });
    });

    it("replaces entire data model at root path", () => {
      processor.processMessage({
        version: "v0.10",
        updateDataModel: {
          surfaceId: "s1",
          path: "/",
          value: { name: "Alice", age: 30 },
        },
      });

      const surface = processor.getSurface("s1")!;
      expect(surface.dataModel).toEqual({ name: "Alice", age: 30 });
    });

    it("replaces entire data model with default path", () => {
      processor.processMessage({
        version: "v0.10",
        updateDataModel: {
          surfaceId: "s1",
          value: { items: [1, 2, 3] },
        },
      });

      expect(processor.getSurface("s1")?.dataModel).toEqual({
        items: [1, 2, 3],
      });
    });

    it("sets value at nested path", () => {
      processor.processMessage({
        version: "v0.10",
        updateDataModel: {
          surfaceId: "s1",
          path: "/user/name",
          value: "Bob",
        },
      });

      expect(processor.getSurface("s1")?.dataModel).toEqual({
        user: { name: "Bob" },
      });
    });

    it("removes value when value is undefined", () => {
      // First set some data
      processor.processMessage({
        version: "v0.10",
        updateDataModel: {
          surfaceId: "s1",
          path: "/",
          value: { foo: "bar", baz: "qux" },
        },
      });

      // Then remove a field (no value property = undefined)
      processor.processMessage({
        version: "v0.10",
        updateDataModel: {
          surfaceId: "s1",
          path: "/foo",
        },
      });

      expect(processor.getSurface("s1")?.dataModel).toEqual({ baz: "qux" });
    });

    it("clears data model when root path has no value", () => {
      processor.processMessage({
        version: "v0.10",
        updateDataModel: {
          surfaceId: "s1",
          path: "/",
          value: { data: "test" },
        },
      });

      processor.processMessage({
        version: "v0.10",
        updateDataModel: {
          surfaceId: "s1",
          path: "/",
        },
      });

      expect(processor.getSurface("s1")?.dataModel).toEqual({});
    });

    it("handles JSON Pointer escapes (~0, ~1)", () => {
      processor.processMessage({
        version: "v0.10",
        updateDataModel: {
          surfaceId: "s1",
          path: "/a~1b",
          value: "slash-key",
        },
      });

      // ~1 decodes to /
      expect(processor.getSurface("s1")?.dataModel).toEqual({
        "a/b": "slash-key",
      });
    });

    it("warns for unknown surface", () => {
      const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

      processor.processMessage({
        version: "v0.10",
        updateDataModel: {
          surfaceId: "unknown",
          path: "/foo",
          value: "bar",
        },
      });

      expect(warn).toHaveBeenCalledWith(expect.stringContaining("unknown surface"));
      warn.mockRestore();
    });
  });

  // ── deleteSurface ──

  describe("deleteSurface", () => {
    it("removes a surface", () => {
      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s1", catalogId: "cat" },
      });

      processor.processMessage({
        version: "v0.10",
        deleteSurface: { surfaceId: "s1" },
      });

      expect(processor.getSurface("s1")).toBeUndefined();
    });

    it("notifies listeners on delete", () => {
      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s1", catalogId: "cat" },
      });

      const listener = vi.fn();
      processor.onChange(listener);

      processor.processMessage({
        version: "v0.10",
        deleteSurface: { surfaceId: "s1" },
      });

      expect(listener).toHaveBeenCalledWith("s1");
    });
  });

  // ── Version filtering ──

  describe("version filtering", () => {
    it("ignores messages without v0.10 version", () => {
      processor.processMessage({
        version: "v0.9",
        createSurface: { surfaceId: "s1", catalogId: "cat" },
      } as Record<string, unknown>);

      expect(processor.getSurface("s1")).toBeUndefined();
    });

    it("ignores messages with no version", () => {
      processor.processMessage({
        type: "stream_start",
        messageId: "msg-1",
      });

      expect(processor.getSurfaceIds()).toEqual([]);
    });
  });

  // ── Query methods ──

  describe("query methods", () => {
    beforeEach(() => {
      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s1", catalogId: "cat" },
      });
      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s2", catalogId: "cat" },
      });
    });

    it("getSurfaceIds returns all IDs", () => {
      const ids = processor.getSurfaceIds();
      expect(ids).toHaveLength(2);
      expect(ids).toContain("s1");
      expect(ids).toContain("s2");
    });

    it("getRenderableSurfaces returns only surfaces with root", () => {
      processor.processMessage({
        version: "v0.10",
        updateComponents: {
          surfaceId: "s1",
          components: [{ id: "root", component: "Column" }],
        },
      });

      const renderable = processor.getRenderableSurfaces();
      expect(renderable).toHaveLength(1);
      expect(renderable[0]?.surfaceId).toBe("s1");
    });

    it("getRenderableSurfaces returns empty when no roots", () => {
      expect(processor.getRenderableSurfaces()).toHaveLength(0);
    });
  });

  // ── Listeners ──

  describe("listeners", () => {
    it("unsubscribes via returned function", () => {
      const listener = vi.fn();
      const unsub = processor.onChange(listener);

      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s1", catalogId: "cat" },
      });
      expect(listener).toHaveBeenCalledTimes(1);

      unsub();

      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s2", catalogId: "cat" },
      });
      expect(listener).toHaveBeenCalledTimes(1); // no more calls
    });
  });

  // ── Reset ──

  describe("reset", () => {
    it("clears surfaces but keeps listeners", () => {
      const listener = vi.fn();
      processor.onChange(listener);

      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s1", catalogId: "cat" },
      });

      processor.reset();

      expect(processor.getSurfaceIds()).toEqual([]);
      expect(processor.getSurface("s1")).toBeUndefined();

      // Listener should still be active after reset
      processor.processMessage({
        version: "v0.10",
        createSurface: { surfaceId: "s2", catalogId: "cat" },
      });
      // listener called once before reset + once after reset
      expect(listener).toHaveBeenCalledTimes(2);
    });
  });
});
