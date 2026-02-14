/**
 * A2UI TextField component.
 *
 * Supports types: text, number, email, password, date, multiline.
 * Writes to data model via onAction.
 */

import { useState } from "react";
import { nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString } from "../data-binding";

export const A2UITextField: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label, surface);
  const placeholder = resolveString(component.placeholder ?? "", surface);
  const inputType = (component.inputType as string) ?? "text";
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const required = component.required ? resolveBoolean(component.required, surface) : false;
  const initialValue = resolveString(component.value ?? "", surface);

  const [value, setValue] = useState(initialValue);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    setValue(newValue);

    if (onAction) {
      onAction({
        name: "change",
        surfaceId: surface.surfaceId,
        sourceComponentId: component.id,
        timestamp: nowISO(),
        context: { value: newValue },
      });
    }
  };

  const isMultiline = inputType === "multiline" || inputType === "textarea";

  return (
    <div className="a2ui-textfield" data-component-id={component.id}>
      {label && (
        <label className="a2ui-textfield__label">
          {label}
          {required && <span className="a2ui-field-required"> *</span>}
        </label>
      )}
      {isMultiline ? (
        <textarea
          className="a2ui-textfield__input a2ui-textfield__input--multiline"
          placeholder={placeholder}
          disabled={disabled}
          value={value}
          onChange={handleChange}
          rows={4}
        />
      ) : (
        <input
          className="a2ui-textfield__input"
          type={inputType}
          placeholder={placeholder}
          disabled={disabled}
          value={value}
          onChange={handleChange}
        />
      )}
    </div>
  );
};
