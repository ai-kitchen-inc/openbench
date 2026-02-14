/**
 * ObCodeBlock — OpenBench custom syntax-highlighted code block.
 *
 * Uses Shiki token API for safe React-based syntax highlighting.
 * No innerHTML or dangerouslySetInnerHTML — all tokens are rendered
 * as React <span> elements with inline styles.
 */

import type React from "react";
import { useEffect, useState } from "react";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString } from "../data-binding";

interface TokenStyle {
  color?: string;
  fontStyle?: string;
  fontWeight?: string;
}

interface StyledToken {
  content: string;
  style: TokenStyle;
}

export const ObCodeBlock: A2UIComponentRenderer = ({ component, surface }) => {
  const code = resolveString(component.code, surface);
  const language = resolveString(component.language ?? "text", surface);
  const showLineNumbers = component.showLineNumbers
    ? resolveBoolean(component.showLineNumbers, surface)
    : true;
  const maxHeight = (component.maxHeight as string) ?? "400px";

  const [tokens, setTokens] = useState<StyledToken[][] | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function highlight() {
      try {
        const shiki = await import("shiki");
        const highlighter = await shiki.createHighlighter({
          themes: ["github-dark"],
          langs: [language as Parameters<typeof shiki.createHighlighter>[0]["langs"][number]],
        });

        const result = highlighter.codeToTokens(code, {
          lang: language as Parameters<typeof highlighter.codeToTokens>[1]["lang"],
          theme: "github-dark",
        });

        if (!cancelled) {
          const styledLines: StyledToken[][] = result.tokens.map((line) =>
            line.map((token) => ({
              content: token.content,
              style: {
                color: token.color,
                fontStyle: token.fontStyle === 1 ? "italic" : undefined,
                fontWeight: token.fontStyle === 2 ? "bold" : undefined,
              },
            })),
          );
          setTokens(styledLines);
        }
        highlighter.dispose();
      } catch {
        if (!cancelled) setTokens(null);
      }
    }

    highlight();
    return () => {
      cancelled = true;
    };
  }, [code, language]);

  const lines = code.split("\n");
  const lineNumWidth = String(lines.length).length;

  const renderLine = (lineNum: number, content: React.ReactNode) => (
    <div key={lineNum} className="ob-code-block__line" style={{ display: "flex" }}>
      {showLineNumbers && (
        <span
          className="ob-code-block__line-num"
          style={{
            display: "inline-block",
            width: `${lineNumWidth + 1}ch`,
            textAlign: "right",
            paddingRight: "1ch",
            opacity: 0.5,
            userSelect: "none",
            flexShrink: 0,
          }}
        >
          {lineNum}
        </span>
      )}
      <span style={{ flex: 1 }}>{content}</span>
    </div>
  );

  return (
    <div
      className="ob-code-block"
      data-component-id={component.id}
      style={{
        maxHeight,
        overflowY: "auto",
        borderRadius: "8px",
        fontSize: "0.875rem",
        lineHeight: 1.5,
      }}
    >
      <pre
        style={{
          margin: 0,
          padding: "16px",
          backgroundColor: "#24292e",
          color: "#e1e4e8",
          overflow: "auto",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        }}
      >
        <code>
          {tokens
            ? tokens.map((line, lineIdx) =>
                renderLine(
                  lineIdx + 1,
                  line.map((token, tokenIdx) => (
                    <span
                      key={tokenIdx}
                      style={{
                        color: token.style.color,
                        fontStyle: token.style.fontStyle as React.CSSProperties["fontStyle"],
                        fontWeight: token.style.fontWeight as React.CSSProperties["fontWeight"],
                      }}
                    >
                      {token.content}
                    </span>
                  )),
                ),
              )
            : lines.map((line, i) => renderLine(i + 1, line))}
        </code>
      </pre>
    </div>
  );
};
