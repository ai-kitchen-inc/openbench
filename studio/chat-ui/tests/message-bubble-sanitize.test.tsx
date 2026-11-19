/**
 * MessageBubble must never turn message text into executable markup.
 *
 * Message text can carry HTML that originated in a web page, an uploaded
 * file or a shared source. These tests pin the sanitizer: dangerous elements
 * and attributes are dropped, ordinary formatting and math still render.
 */

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "../src/components/MessageBubble";
import type { ChatMessage } from "../src/types";

function renderText(content: string): HTMLElement {
  const message: ChatMessage = {
    id: "m1",
    role: "assistant",
    content,
    timestamp: new Date().toISOString(),
    status: "complete",
  };
  const { container } = render(<MessageBubble message={message} />);
  const text = container.querySelector(".chat-message__text");
  if (!(text instanceof HTMLElement)) throw new Error("message text not rendered");
  return text;
}

describe("MessageBubble HTML sanitizing", () => {
  it.each([
    ["script", "before <script>window.__pwned = 1</script> after", "script"],
    ["iframe srcdoc", "<iframe srcdoc=\"<script>parent.x=1</script>\"></iframe>", "iframe"],
    ["plain iframe", '<iframe src="https://evil.example/"></iframe>', "iframe"],
    ["style", "<style>body{display:none}</style>text", "style"],
    ["form", '<form action="https://evil.example/"><input name="q"></form>', "form"],
    ["object", '<object data="https://evil.example/x.swf"></object>', "object"],
    ["embed", '<embed src="https://evil.example/x">', "embed"],
    ["link", '<link rel="stylesheet" href="https://evil.example/x.css">', "link"],
    ["meta refresh", '<meta http-equiv="refresh" content="0;url=https://evil.example/">', "meta"],
    ["base", '<base href="https://evil.example/">', "base"],
  ])("drops <%s>", (_label, markdown, selector) => {
    const text = renderText(markdown);
    expect(text.querySelector(selector)).toBeNull();
  });

  it("strips inline event handlers", () => {
    const text = renderText('<img src="x.png" onerror="window.__pwned = 1" alt="pic">');
    const img = text.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("onerror")).toBeNull();
    expect(text.innerHTML).not.toContain("onerror");
  });

  it("strips javascript: URLs from raw links and markdown links", () => {
    const text = renderText(
      '<a href="javascript:alert(1)">raw</a> and [md](javascript:alert(1)) and [ok](https://example.com/)',
    );
    const hrefs = Array.from(text.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "");
    expect(hrefs.some((href) => href.toLowerCase().startsWith("javascript:"))).toBe(false);
    expect(hrefs).toContain("https://example.com/");
  });

  it("strips style attributes", () => {
    const text = renderText('<span style="position:fixed;inset:0">overlay</span>');
    expect(text.querySelector("[style]")).toBeNull();
    expect(text.textContent).toContain("overlay");
  });

  it("keeps ordinary formatting", () => {
    const text = renderText(
      [
        "| a | b |",
        "|---|---|",
        "| 1 | 2 |",
        "",
        "line one<br>line two",
        "",
        "<details><summary>More</summary>hidden text</details>",
        "",
        "**bold** and `code`",
      ].join("\n"),
    );
    expect(text.querySelector("table")).not.toBeNull();
    expect(text.querySelectorAll("td")).toHaveLength(2);
    expect(text.querySelector("br")).not.toBeNull();
    expect(text.querySelector("details summary")?.textContent).toBe("More");
    expect(text.querySelector("strong")?.textContent).toBe("bold");
    expect(text.querySelector("code")?.textContent).toBe("code");
  });

  it("still renders inline and block math", () => {
    const text = renderText(["Inline $$a^2 + b^2$$ here.", "", "$$", "\\frac{1}{2}", "$$"].join("\n"));
    expect(text.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(2);
    expect(text.querySelector(".katex-display")).not.toBeNull();
  });

  it("keeps footnote links pointing at their targets", () => {
    const text = renderText(["Claim.[^1]", "", "[^1]: Source."].join("\n"));
    const ref = text.querySelector("sup a");
    const href = ref?.getAttribute("href") ?? "";
    expect(href.startsWith("#")).toBe(true);
    expect(text.querySelector(`[id="${href.slice(1)}"]`)).not.toBeNull();
  });
});
