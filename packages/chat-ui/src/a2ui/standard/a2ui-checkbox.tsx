/**
 * A2UI CheckBox component.
 */

import { useState } from "react";
import { nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString } from "../data-binding";

export const A2UICheckBox: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label, surface);
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const initialChecked = component.checked ? resolveBoolean(component.checked, surface) : false;

  const [checked, setChecked] = useState(initialChecked);

  const handleChange = () => {
    const newVal = !checked;
    setChecked(newVal);

    if (onAction) {
      onAction({
        name: "change",
        surfaceId: surface.surfaceId,
        sourceComponentId: component.id,
        timestamp: nowISO(),
        context: { checked: newVal },
      });
    }
  };

  return (
    <label className="a2ui-checkbox" data-component-id={component.id}>
      <input
        type="checkbox"
        className="a2ui-checkbox__input"
        checked={checked}
        disabled={disabled}
        onChange={handleChange}
      />
      <span className="a2ui-checkbox__label">{label}</span>
    </label>
  );
};
