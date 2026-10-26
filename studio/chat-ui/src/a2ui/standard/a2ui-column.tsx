/**
 * A2UI Column component.
 *
 * Vertical flex layout container.
 */

import type { A2UIComponentRenderer } from "../../types";

export const A2UIColumn: A2UIComponentRenderer = ({ component, children }) => {
  const gap = (component.gap as string) ?? "8px";
  const align = (component.alignItems as string) ?? "stretch";
  const justify = (component.justifyContent as string) ?? "flex-start";

  return (
    <div
      className="a2ui-column"
      data-component-id={component.id}
      style={{
        display: "flex",
        flexDirection: "column",
        gap,
        alignItems: align,
        justifyContent: justify,
      }}
    >
      {children}
    </div>
  );
};
