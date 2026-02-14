/**
 * A2UI DateTimeInput component.
 */

import { useState } from "react";
import { nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString } from "../data-binding";

export const A2UIDateTimeInput: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label ?? "", surface);
  const inputType = (component.inputType as string) ?? "date";
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const initialValue = resolveString(component.value ?? "", surface);

  const [value, setValue] = useState(initialValue);

  // Map A2UI input types to HTML input types
  const htmlType = inputType === "datetime" ? "datetime-local" : inputType;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
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
    <div className="a2ui-datetime-input" data-component-id={component.id}>
      {label && <label className="a2ui-datetime-input__label">{label}</label>}
      <input
        className="a2ui-datetime-input__input"
        type={htmlType}
        value={value}
        disabled={disabled}
        onChange={handleChange}
      />
    </div>
  );
};
