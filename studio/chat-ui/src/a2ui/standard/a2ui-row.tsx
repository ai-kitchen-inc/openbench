/**
 * A2UI Row component.
 *
 * Horizontal flex layout container.
 */

import type { A2UIComponentRenderer } from "../../types";

export const A2UIRow: A2UIComponentRenderer = ({ component, children }) => {
  const gap = (component.gap as string) ?? "8px";
  const align = (component.alignItems as string) ?? "center";
  const justify = (component.justifyContent as string) ?? "flex-start";
  const wrap = (component.wrap as boolean) ? "wrap" : "nowrap";

  return (
    <div
      className="a2ui-row"
      data-component-id={component.id}
      style={{
        display: "flex",
        flexDirection: "row",
        gap,
        alignItems: align,
        justifyContent: justify,
        flexWrap: wrap,
      }}
    >
      {children}
    </div>
  );
};
