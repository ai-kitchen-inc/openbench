/**
 * Tests for ObMarkdown — markdown + math/LaTeX rendering.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ObMarkdown } from "../src/a2ui/custom/ob-markdown";
import type { A2UIComponent, A2UISurface } from "../src/types";

function makeSurface(dataModel: Record<string, unknown> = {}): A2UISurface {
  return {
    surfaceId: "test-surface",
    catalogId: "test",
    components: new Map(),
    dataModel,
  };
}

function makeComponent(content: string): A2UIComponent {
  return {
    id: "md-test",
    component: "ObMarkdown",
    content,
  } as A2UIComponent;
}

describe("ObMarkdown", () => {
  it("renders basic markdown text", () => {
    const component = makeComponent("Hello **world**");
    const surface = makeSurface();

    render(<ObMarkdown component={component} surface={surface} />);

    expect(screen.getByText("world")).toBeDefined();
  });

  it("renders headings", () => {
    const component = makeComponent("# Title\n\nSome body text");
    const surface = makeSurface();

    const { container } = render(<ObMarkdown component={component} surface={surface} />);

    const h1 = container.querySelector("h1");
    expect(h1).not.toBeNull();
    expect(h1?.textContent).toBe("Title");
  });

  it("renders inline math ($...$) without crashing", () => {
    const component = makeComponent("The formula is $E = mc^2$ here.");
    const surface = makeSurface();

    const { container } = render(<ObMarkdown component={component} surface={surface} />);

    // KaTeX wraps math in .katex spans
    const katexEl = container.querySelector(".katex");
    expect(katexEl).not.toBeNull();
  });

  it("renders display math ($$...$$) without crashing", () => {
    const component = makeComponent("Below is a formula:\n\n$$\\sum_{i=1}^n x_i$$\n\nEnd.");
    const surface = makeSurface();

    const { container } = render(<ObMarkdown component={component} surface={surface} />);

    // KaTeX renders math in .katex spans (display math may use .katex-display or .katex-html)
    const katexEl = container.querySelector(".katex");
    expect(katexEl).not.toBeNull();
  });

  it("renders mixed markdown and math", () => {
    const component = makeComponent(
      "# Math Section\n\nThe quadratic formula is $x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$.\n\n$$a^2 + b^2 = c^2$$",
    );
    const surface = makeSurface();

    const { container } = render(<ObMarkdown component={component} surface={surface} />);

    // Should have both heading and katex elements
    expect(container.querySelector("h1")).not.toBeNull();
    expect(container.querySelector(".katex")).not.toBeNull();
  });

  it("renders currency dollar signs as literal text, not math", () => {
    const component = makeComponent("Solar costs $0.03/kWh for solar and $0.034/kWh for wind.");
    const surface = makeSurface();

    const { container } = render(<ObMarkdown component={component} surface={surface} />);

    // Currency should NOT trigger KaTeX math rendering
    const katexEl = container.querySelector(".katex");
    expect(katexEl).toBeNull();

    // The dollar signs should appear as literal text
    const text = container.textContent ?? "";
    expect(text).toContain("$0.03");
    expect(text).toContain("$0.034");
  });

  it("has ob-markdown class and data-component-id", () => {
    const component = makeComponent("Test");
    const surface = makeSurface();

    const { container } = render(<ObMarkdown component={component} surface={surface} />);

    const wrapper = container.querySelector(".ob-markdown");
    expect(wrapper).not.toBeNull();
    expect(wrapper?.getAttribute("data-component-id")).toBe("md-test");
  });
});
