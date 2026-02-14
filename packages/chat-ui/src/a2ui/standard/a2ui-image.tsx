/**
 * A2UI Image component.
 */

import type { A2UIComponentRenderer } from "../../types";
import { resolveString } from "../data-binding";

export const A2UIImage: A2UIComponentRenderer = ({ component, surface }) => {
  const src = resolveString(component.src ?? component.url, surface);
  const alt = resolveString(component.alt ?? component.description ?? "", surface);
  const width = (component.width as string) ?? undefined;
  const height = (component.height as string) ?? undefined;

  return (
    <img
      className="a2ui-image"
      data-component-id={component.id}
      src={src}
      alt={alt}
      style={{
        width,
        height,
        maxWidth: "100%",
        borderRadius: "4px",
      }}
    />
  );
};
