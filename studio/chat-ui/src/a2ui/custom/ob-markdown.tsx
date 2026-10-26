/**
 * ObMarkdown — OpenBench custom markdown renderer.
 *
 * Uses react-markdown with remark-math + rehype-katex for LaTeX rendering.
 * Single-dollar math ($...$) is disabled to prevent currency signs from
 * being misinterpreted as inline math. Use $$...$$ for math blocks.
 */

import "katex/dist/katex.min.css";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { A2UIComponentRenderer } from "../../types";
import { resolveString } from "../data-binding";

export const ObMarkdown: A2UIComponentRenderer = ({ component, surface }) => {
  const content = resolveString(component.content, surface);

  return (
    <div className="ob-markdown" data-component-id={component.id}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
        rehypePlugins={[rehypeKatex]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};
