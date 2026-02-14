/**
 * Tests for SurfaceRenderer — A2UI surface → React component tree.
 */

import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { registerCustomComponent } from "../src/a2ui/catalog";
import { SurfaceRenderer } from "../src/a2ui/surface-renderer";
import type { A2UIAction, A2UIComponent, A2UISurface } from "../src/types";

/** Helper to create a surface with given components. */
function makeSurface(
  components: A2UIComponent[],
  dataModel: Record<string, unknown> = {},
): A2UISurface {
  const map = new Map<string, A2UIComponent>();
  for (const c of components) {
    map.set(c.id, c);
  }
  return {
    surfaceId: "test-surface",
    catalogId: "test",
    components: map,
    dataModel,
  };
}

describe("SurfaceRenderer", () => {
  // ── Basic rendering ──

  describe("basic rendering", () => {
    it("renders nothing when no root component", () => {
      const surface = makeSurface([{ id: "text1", component: "Text", text: "Hello" }]);

      const { container } = render(<SurfaceRenderer surface={surface} />);
      expect(container.innerHTML).toBe("");
    });

    it("renders root component", () => {
      const surface = makeSurface([{ id: "root", component: "Column" }]);

      const { container } = render(<SurfaceRenderer surface={surface} />);
      expect(container.querySelector(".a2ui-surface")).not.toBeNull();
      expect(container.querySelector(".a2ui-column")).not.toBeNull();
    });

    it("renders Text component", () => {
      const surface = makeSurface([
        { id: "root", component: "Column", children: ["text1"] },
        { id: "text1", component: "Text", text: "Hello World" },
      ]);

      render(<SurfaceRenderer surface={surface} />);
      expect(screen.getByText("Hello World")).toBeDefined();
    });

    it("renders nested tree", () => {
      const surface = makeSurface([
        { id: "root", component: "Column", children: ["card1"] },
        { id: "card1", component: "Card", children: ["text1", "text2"] },
        { id: "text1", component: "Text", text: "Title", variant: "h2" },
        { id: "text2", component: "Text", text: "Body text" },
      ]);

      render(<SurfaceRenderer surface={surface} />);
      expect(screen.getByText("Title")).toBeDefined();
      expect(screen.getByText("Body text")).toBeDefined();
    });
  });

  // ── Layout components ──

  describe("layout components", () => {
    it("renders Row with flex direction row", () => {
      const surface = makeSurface([
        { id: "root", component: "Row", children: ["t1", "t2"] },
        { id: "t1", component: "Text", text: "Left" },
        { id: "t2", component: "Text", text: "Right" },
      ]);

      const { container } = render(<SurfaceRenderer surface={surface} />);
      const row = container.querySelector(".a2ui-row");
      expect(row).not.toBeNull();
      expect(row?.getAttribute("style")).toContain("row");
    });

    it("renders Card with shadow", () => {
      const surface = makeSurface([{ id: "root", component: "Card", elevation: 2 }]);

      const { container } = render(<SurfaceRenderer surface={surface} />);
      expect(container.querySelector(".a2ui-card")).not.toBeNull();
    });

    it("renders Divider", () => {
      const surface = makeSurface([
        { id: "root", component: "Column", children: ["d1"] },
        { id: "d1", component: "Divider" },
      ]);

      const { container } = render(<SurfaceRenderer surface={surface} />);
      expect(container.querySelector(".a2ui-divider")).not.toBeNull();
    });
  });

  // ── Data binding ──

  describe("data binding", () => {
    it("resolves text from data model", () => {
      const surface = makeSurface(
        [{ id: "root", component: "Text", text: { path: "/greeting" } }],
        { greeting: "Hello from data model!" },
      );

      render(<SurfaceRenderer surface={surface} />);
      expect(screen.getByText("Hello from data model!")).toBeDefined();
    });

    it("resolves nested data binding", () => {
      const surface = makeSurface(
        [{ id: "root", component: "Text", text: { path: "/user/name" } }],
        { user: { name: "Alice" } },
      );

      render(<SurfaceRenderer surface={surface} />);
      expect(screen.getByText("Alice")).toBeDefined();
    });
  });

  // ── Interactive components ──

  describe("interactive components", () => {
    it("Button dispatches action on click", async () => {
      const onAction = vi.fn();
      const surface = makeSurface([
        {
          id: "root",
          component: "Button",
          label: "Click Me",
          action: {
            event: {
              name: "submit",
              context: { form: "test" },
            },
          },
        },
      ]);

      render(<SurfaceRenderer surface={surface} onAction={onAction} />);

      const button = screen.getByText("Click Me");
      await userEvent.click(button);

      expect(onAction).toHaveBeenCalledTimes(1);
      const action: A2UIAction = onAction.mock.calls[0]?.[0];
      expect(action.name).toBe("submit");
      expect(action.surfaceId).toBe("test-surface");
      expect(action.sourceComponentId).toBe("root");
      expect(action.context).toEqual({ form: "test" });
    });

    it("Image renders with src", () => {
      const surface = makeSurface([
        { id: "root", component: "Image", src: "https://example.com/img.png", alt: "Test" },
      ]);

      const { container } = render(<SurfaceRenderer surface={surface} />);
      const img = container.querySelector("img");
      expect(img).not.toBeNull();
      expect(img?.getAttribute("src")).toBe("https://example.com/img.png");
      expect(img?.getAttribute("alt")).toBe("Test");
    });
  });

  // ── Unknown components ──

  describe("unknown components", () => {
    let warnSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    });

    afterEach(() => {
      warnSpy.mockRestore();
    });

    it("renders null for unknown component type", () => {
      const surface = makeSurface([{ id: "root", component: "UnknownWidget" }]);

      const { container } = render(<SurfaceRenderer surface={surface} />);
      // The surface wrapper exists but nothing inside
      const surfaceEl = container.querySelector(".a2ui-surface");
      expect(surfaceEl?.children).toHaveLength(0);
    });

    it("skips missing child component", () => {
      const surface = makeSurface([
        { id: "root", component: "Column", children: ["existing", "missing"] },
        { id: "existing", component: "Text", text: "I exist" },
        // 'missing' ID is not in the map
      ]);

      render(<SurfaceRenderer surface={surface} />);
      expect(screen.getByText("I exist")).toBeDefined();
    });
  });

  // ── Custom component registration ──

  describe("custom component registration", () => {
    it("renders user-registered custom component", () => {
      const MyWidget: React.FC<{ component: A2UIComponent }> = ({ component }) => (
        <div data-testid="my-widget">{String(component.message)}</div>
      );

      registerCustomComponent("MyWidget", MyWidget as any);

      const surface = makeSurface([{ id: "root", component: "MyWidget", message: "Custom!" }]);

      render(<SurfaceRenderer surface={surface} />);
      expect(screen.getByTestId("my-widget").textContent).toBe("Custom!");
    });
  });

  // ── Surface attributes ──

  describe("surface attributes", () => {
    it("sets data-surface-id on wrapper", () => {
      const surface = makeSurface([{ id: "root", component: "Column" }]);

      const { container } = render(<SurfaceRenderer surface={surface} />);
      expect(container.querySelector('[data-surface-id="test-surface"]')).not.toBeNull();
    });

    it("sets data-component-id on components", () => {
      const surface = makeSurface([{ id: "root", component: "Text", text: "Hello" }]);

      const { container } = render(<SurfaceRenderer surface={surface} />);
      expect(container.querySelector('[data-component-id="root"]')).not.toBeNull();
    });
  });
});
