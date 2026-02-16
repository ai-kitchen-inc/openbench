/**
 * A2UI Divider component.
 */

import type { A2UIComponentRenderer } from "../../types";

export const A2UIDivider: A2UIComponentRenderer = ({ component }) => {
  const orientation = (component.orientation as string) ?? "horizontal";
  const isVertical = orientation === "vertical";

  return (
    <hr
      className={`a2ui-divider a2ui-divider--${orientation}`}
      data-component-id={component.id}
      style={{
        border: "none",
        borderTop: isVertical ? "none" : "1px solid var(--ob-divider-color, #e0e0e0)",
        borderLeft: isVertical ? "1px solid var(--ob-divider-color, #e0e0e0)" : "none",
        margin: isVertical ? "0 8px" : "8px 0",
        alignSelf: isVertical ? "stretch" : undefined,
      }}
    />
  );
};
