/**
 * A2UI Icon component.
 *
 * Renders a Material Symbols icon name as text with the icon font class.
 */

import type { A2UIComponentRenderer } from "../../types";
import { resolveString } from "../data-binding";

export const A2UIIcon: A2UIComponentRenderer = ({ component, surface }) => {
  const icon = resolveString(component.icon ?? component.name, surface);
  const size = (component.size as string) ?? "24px";
  const color = (component.color as string) ?? "currentColor";

  return (
    <span
      className="a2ui-icon material-symbols-outlined"
      data-component-id={component.id}
      style={{ fontSize: size, color }}
      aria-hidden="true"
    >
      {icon}
    </span>
  );
};
