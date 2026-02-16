/**
 * A2UI DateTimeInput component.
 *
 * Evaluates checks for validation.
 */

import { useState } from "react";
import { nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { evaluateChecks, resolveBoolean, resolveString } from "../data-binding";

export const A2UIDateTimeInput: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label ?? "", surface);
  const inputType = (component.inputType as string) ?? "date";
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const required = component.required ? resolveBoolean(component.required, surface) : false;
  const initialValue = resolveString(component.value ?? "", surface);

  const [value, setValue] = useState(initialValue);
  const [touched, setTouched] = useState(false);

  const checks = Array.isArray(component.checks) ? component.checks : [];
  const errors = touched ? evaluateChecks(checks, value, surface) : [];
  const hasError = errors.length > 0;

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

  const handleBlur = () => setTouched(true);
  const wrapperClass = `a2ui-datetime-input${hasError ? " a2ui-datetime-input--error" : ""}`;

  return (
    <div className={wrapperClass} data-component-id={component.id}>
      {label && (
        <label className="a2ui-datetime-input__label">
          {label}
          {required && <span className="a2ui-field-required"> *</span>}
        </label>
      )}
      <input
        className="a2ui-datetime-input__input"
        type={htmlType}
        value={value}
        disabled={disabled}
        onChange={handleChange}
        onBlur={handleBlur}
      />
      {errors.map((msg, i) => (
        <div key={i} className="a2ui-field-error">
          {msg}
        </div>
      ))}
    </div>
  );
};
