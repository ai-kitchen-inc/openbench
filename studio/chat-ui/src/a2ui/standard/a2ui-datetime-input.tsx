/**
 * A2UI DateTimeInput component.
 *
 * Writes to surface.dataModel via setAtPath. Evaluates checks for validation.
 */

import { useEffect, useRef, useState } from "react";
import { isDataBinding } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { evaluateChecks, resolveBoolean, resolveString, setAtPath } from "../data-binding";

export const A2UIDateTimeInput: A2UIComponentRenderer = ({ component, surface }) => {
  const label = resolveString(component.label ?? "", surface);
  const inputType = (component.inputType as string) ?? "date";
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const required = component.required ? resolveBoolean(component.required, surface) : false;

  const bindingPath = isDataBinding(component.value)
    ? (component.value as { path: string }).path
    : null;

  const [value, setValue] = useState(() => {
    const initial = resolveString(component.value ?? "", surface);
    if (bindingPath) setAtPath(surface.dataModel, bindingPath, initial);
    return initial;
  });
  const [touched, setTouched] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Listen for a2ui-validate event (dispatched by Button on form submit)
  useEffect(() => {
    const el = wrapperRef.current?.closest("[data-surface-id]");
    if (!el) return;
    const handler = () => setTouched(true);
    el.addEventListener("a2ui-validate", handler);
    return () => el.removeEventListener("a2ui-validate", handler);
  }, []);

  const checks = Array.isArray(component.checks) ? component.checks : [];
  const errors = touched ? evaluateChecks(checks, value, surface) : [];
  const hasError = errors.length > 0;

  // Map A2UI input types to HTML input types
  const htmlType = inputType === "datetime" ? "datetime-local" : inputType;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newVal = e.target.value;
    setValue(newVal);
    if (bindingPath) setAtPath(surface.dataModel, bindingPath, newVal);
  };

  const handleBlur = () => setTouched(true);
  const wrapperClass = `a2ui-datetime-input${hasError ? " a2ui-datetime-input--error" : ""}`;

  return (
    <div className={wrapperClass} data-component-id={component.id} ref={wrapperRef}>
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
