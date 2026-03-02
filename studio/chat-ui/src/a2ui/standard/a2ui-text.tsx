/**
 * A2UI Text component.
 *
 * Renders text with semantic variant (h1–h5, body, caption, overline).
 */

import type React from "react";
import type { A2UIComponentRenderer } from "../../types";
import { resolveString } from "../data-binding";

const VARIANT_TAGS: Record<string, keyof React.JSX.IntrinsicElements> = {
  h1: "h1",
  h2: "h2",
  h3: "h3",
  h4: "h4",
  h5: "h5",
  body: "p",
  caption: "span",
  overline: "span",
};

export const A2UIText: A2UIComponentRenderer = ({ component, surface }) => {
  const text = resolveString(component.text, surface);
  const variant = (component.variant as string) ?? "body";
  const Tag = VARIANT_TAGS[variant] ?? "p";

  return (
    <Tag className={`a2ui-text a2ui-text--${variant}`} data-component-id={component.id}>
      {text}
    </Tag>
  );
};
