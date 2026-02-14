/**
 * A2UI ChoicePicker component.
 *
 * Custom styled dropdown select with chevron icon.
 */

import { useState } from "react";
import { nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString } from "../data-binding";

export const A2UIChoicePicker: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label ?? "", surface);
  const options = (component.options as Array<{ label: unknown; value: unknown }>) ?? [];
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const required = component.required ? resolveBoolean(component.required, surface) : false;
  const initialValue = resolveString(component.value ?? "", surface);
  const placeholder = resolveString(component.placeholder ?? "Select...", surface);

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
      {label && (
        <label className="a2ui-choice-picker__label">
          {label}
          {required && <span className="a2ui-field-required"> *</span>}
        </label>
      )}
      <div className="a2ui-choice-picker__wrapper">
        <select
          className="a2ui-choice-picker__select"
          value={value}
          disabled={disabled}
          onChange={handleChange}
        >
          <option value="">{placeholder}</option>
          {options.map((opt, i) => (
            <option key={i} value={resolveString(opt.value, surface)}>
              {resolveString(opt.label, surface)}
            </option>
          ))}
        </select>
        <svg
          className="a2ui-choice-picker__chevron"
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M4 6L8 10L12 6"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    </div>
  );
};
