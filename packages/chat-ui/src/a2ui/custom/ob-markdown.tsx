/**
 * ObMarkdown — OpenBench custom markdown renderer.
 *
 * Uses react-markdown with remark-math + rehype-katex for LaTeX rendering.
 * Currency dollar signs ($0.03, $100) are escaped to prevent math interpretation.
 */

import "katex/dist/katex.min.css";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { A2UIComponentRenderer } from "../../types";
import { resolveString } from "../data-binding";

/**
 * Escape dollar signs used as currency ($ followed by digit) so remark-math
 * doesn't interpret them as inline math delimiters.
 * e.g. "$0.03/kWh" → "\$0.03/kWh" (renders as literal $)
 */
function escapeCurrencyDollars(text: string): string {
  return text.replace(/\$(?=\d)/g, "\\$");
}

export const ObMarkdown: A2UIComponentRenderer = ({ component, surface }) => {
  const raw = resolveString(component.content, surface);
  const content = escapeCurrencyDollars(raw);

  return (
    <div className="ob-markdown" data-component-id={component.id}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
        {content}
      </ReactMarkdown>
    </div>
  );
};
