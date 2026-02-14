/**
 * A2UI ChoicePicker component.
 *
 * Renders a dropdown select or radio group.
 */

import { useState } from "react";
import { nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString } from "../data-binding";

export const A2UIChoicePicker: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label ?? "", surface);
  const options = (component.options as Array<{ label: unknown; value: unknown }>) ?? [];
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const initialValue = resolveString(component.value ?? "", surface);

  const [value, setValue] = useState(initialValue);

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newVal = e.target.value;
    setValue(newVal);

    if (onAction) {
      onAction({
        name: "change",
        surfaceId: surface.surfaceId,
        sourceComponentId: component.id,
        timestamp: nowISO(),
        context: { value: newVal },
      });
    }
  };

  return (
    <div className="a2ui-choice-picker" data-component-id={component.id}>
      {label && <label className="a2ui-choice-picker__label">{label}</label>}
      <select
        className="a2ui-choice-picker__select"
        value={value}
        disabled={disabled}
        onChange={handleChange}
      >
        <option value="">Select...</option>
        {options.map((opt, i) => (
          <option key={i} value={resolveString(opt.value, surface)}>
            {resolveString(opt.label, surface)}
          </option>
        ))}
      </select>
    </div>
  );
};
