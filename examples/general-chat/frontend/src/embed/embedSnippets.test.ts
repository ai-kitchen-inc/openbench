import { curlSnippet, embedPageUrl, iframeSnippet, maskSecret, redactSecret } from "./embedSnippets";

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
    expect(maskSecret("abcdefghijkl")).toBe("••••••••••••");
    expect(maskSecret("")).toBe("");
  });

  it("redacts raw and url-encoded occurrences of the secret", () => {
    const key = "a b";
    const text = `${embedPageUrl("https://x", "agen", key)} Bearer ${key}`;
    expect(redactSecret(text, key)).toBe("https://x/embed/agen?key=••• Bearer •••");
    expect(redactSecret("no key here", "")).toBe("no key here");
  });
});
