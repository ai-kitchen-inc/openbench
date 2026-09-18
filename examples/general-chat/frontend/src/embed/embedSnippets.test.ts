import { curlSnippet, embedPageUrl, iframeSnippet, maskKey } from "./embedSnippets";

describe("embedSnippets", () => {
  it("builds the embed page url with encoded key", () => {
    expect(embedPageUrl("https://chat.example", "analis-keuangan", "a b")).toBe(
      "https://chat.example/embed/analis-keuangan?key=a%20b",
    );
  });

  it("builds an iframe pointing at the embed page", () => {
    const html = iframeSnippet("https://chat.example", "hr", "k-1");
    expect(html).toContain('src="https://chat.example/embed/hr?key=k-1"');
    expect(html.startsWith("<iframe")).toBe(true);
    expect(html.endsWith("</iframe>")).toBe(true);
  });

  it("builds a streaming curl call against the per-agent SSE endpoint", () => {
    const sh = curlSnippet("https://chat.example", "hr", "k-1");
    expect(sh).toContain("curl -N -X POST https://chat.example/agents/hr/awp");
    expect(sh).toContain('-H "Authorization: Bearer k-1"');
    expect(sh).toContain('"threadId":"t-1"');
    expect(sh).toContain('"role":"user"');
  });

  it("masks keys keeping only the edges", () => {
    expect(maskKey("abcdefghijkl")).toBe("abcd…ijkl");
    expect(maskKey("short")).toBe("•••••");
  });
});
