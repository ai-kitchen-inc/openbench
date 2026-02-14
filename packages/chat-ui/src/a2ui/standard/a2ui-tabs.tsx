/**
 * A2UI Tabs component.
 *
 * Renders a tabbed interface. Each tab has a label and corresponds
 * to a child component (by index in the children array).
 */

import React, { useState } from "react";
import type { A2UIComponentRenderer } from "../../types";
import { resolveString } from "../data-binding";

export const A2UITabs: A2UIComponentRenderer = ({ component, surface, children }) => {
  const tabs = (component.tabs as Array<{ label: unknown }>) ?? [];
  const [activeIndex, setActiveIndex] = useState(0);

  const childArray = React.Children.toArray(children);

  return (
    <div className="a2ui-tabs" data-component-id={component.id}>
      <div className="a2ui-tabs__header" role="tablist">
        {tabs.map((tab, i) => (
          <button
            key={i}
            role="tab"
            className={`a2ui-tabs__tab ${i === activeIndex ? "a2ui-tabs__tab--active" : ""}`}
            aria-selected={i === activeIndex}
            onClick={() => setActiveIndex(i)}
            type="button"
          >
            {resolveString(tab.label, surface)}
          </button>
        ))}
      </div>
      <div className="a2ui-tabs__content" role="tabpanel">
        {childArray[activeIndex] ?? null}
      </div>
    </div>
  );
};
