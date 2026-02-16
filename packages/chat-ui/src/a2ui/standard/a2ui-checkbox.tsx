/**
 * A2UI CheckBox component.
 *
 * Custom Notion-style checkbox with SVG check icon.
 * Evaluates checks for validation.
 */

import { useState } from "react";
import { nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { evaluateChecks, resolveBoolean, resolveString } from "../data-binding";

export const A2UICheckBox: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label, surface);
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const required = component.required ? resolveBoolean(component.required, surface) : false;
  const initialChecked = component.checked ? resolveBoolean(component.checked, surface) : false;

  const [checked, setChecked] = useState(initialChecked);
  const [touched, setTouched] = useState(false);

  const checks = Array.isArray(component.checks) ? component.checks : [];
  const errors = touched ? evaluateChecks(checks, checked, surface) : [];

  const handleChange = () => {
    if (disabled) return;
    const newVal = !checked;
    setChecked(newVal);
    setTouched(true);

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
    <div data-component-id={component.id}>
      <label className={`a2ui-checkbox${disabled ? " a2ui-checkbox--disabled" : ""}`}>
        <input
          type="checkbox"
          className="a2ui-checkbox__native"
          checked={checked}
          disabled={disabled}
          onChange={handleChange}
          tabIndex={-1}
        />
        <span
          className={`a2ui-checkbox__box${checked ? " a2ui-checkbox__box--checked" : ""}`}
          role="checkbox"
          aria-checked={checked}
          tabIndex={disabled ? -1 : 0}
          onKeyDown={(e) => {
            if (e.key === " " || e.key === "Enter") {
              e.preventDefault();
              handleChange();
            }
          }}
        >
          {checked && (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
              <path
                d="M2.5 6L5 8.5L9.5 3.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </span>
        <span className="a2ui-checkbox__label">
          {label}
          {required && <span className="a2ui-field-required"> *</span>}
        </span>
      </label>
      {errors.map((msg, i) => (
        <div key={i} className="a2ui-field-error">
          {msg}
        </div>
      ))}
    </div>
  );
};
