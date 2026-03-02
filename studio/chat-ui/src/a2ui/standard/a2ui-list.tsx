/**
 * A2UI List component.
 *
 * Renders a scrollable list. In A2UI v0.10, the list can use
 * template binding to repeat children for each data item.
 */

import type { A2UIComponentRenderer } from "../../types";

export const A2UIList: A2UIComponentRenderer = ({ component, children }) => {
  const maxHeight = (component.maxHeight as string) ?? undefined;
  const ordered = (component.ordered as boolean) ?? false;
  const Tag = ordered ? "ol" : "ul";

  return (
    <Tag
      className="a2ui-list"
      data-component-id={component.id}
      style={{
        maxHeight,
        overflowY: maxHeight ? "auto" : undefined,
        listStyle: ordered ? "decimal" : "none",
        padding: ordered ? undefined : 0,
        margin: 0,
      }}
    >
      {children}
    </Tag>
  );
};
