/**
 * A2UI Card component.
 *
 * Elevated container with padding.
 */

import type { A2UIComponentRenderer } from "../../types";

export const A2UICard: A2UIComponentRenderer = ({ component, children }) => {
  const elevation = (component.elevation as number) ?? 1;
  const padding = (component.padding as string) ?? "16px";

  const shadow =
    elevation === 0 ? "none" : `0 ${elevation * 2}px ${elevation * 4}px rgba(0,0,0,0.1)`;

  return (
    <div
      className="a2ui-card"
      data-component-id={component.id}
      style={{
        padding,
        borderRadius: "8px",
        boxShadow: shadow,
        backgroundColor: "var(--a2ui-card-bg, #ffffff)",
      }}
    >
      {children}
    </div>
  );
};
