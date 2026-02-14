/**
 * ObMarkdown — OpenBench custom markdown renderer.
 *
 * Uses react-markdown for safe rendering.
 */

import ReactMarkdown from "react-markdown";
import type { A2UIComponentRenderer } from "../../types";
import { resolveString } from "../data-binding";

export const ObMarkdown: A2UIComponentRenderer = ({ component, surface }) => {
  const content = resolveString(component.content, surface);

  return (
    <div className="ob-markdown" data-component-id={component.id}>
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
};
