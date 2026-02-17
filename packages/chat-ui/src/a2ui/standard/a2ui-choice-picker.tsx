/**
 * A2UI ChoicePicker component.
 *
 * Custom styled dropdown select with chevron icon.
 * Writes to surface.dataModel via setAtPath. Evaluates checks for validation.
 */

import { useEffect, useRef, useState } from "react";
import { isDataBinding } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { evaluateChecks, resolveBoolean, resolveString, setAtPath } from "../data-binding";

export const A2UIChoicePicker: A2UIComponentRenderer = ({ component, surface }) => {
  const label = resolveString(component.label ?? "", surface);
  const options = (component.options as Array<{ label: unknown; value: unknown }>) ?? [];
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const required = component.required ? resolveBoolean(component.required, surface) : false;
  const placeholder = resolveString(component.placeholder ?? "Select...", surface);

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

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newVal = e.target.value;
    setValue(newVal);
    setTouched(true);
    if (bindingPath) setAtPath(surface.dataModel, bindingPath, newVal);
  };

  const wrapperClass = `a2ui-choice-picker${hasError ? " a2ui-choice-picker--error" : ""}`;

  return (
    <div className={wrapperClass} data-component-id={component.id} ref={wrapperRef}>
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
          {options.map((opt) => {
            const optValue = resolveString(opt.value, surface);
            return (
              <option key={optValue} value={optValue}>
                {resolveString(opt.label, surface)}
              </option>
            );
          })}
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
      {errors.map((msg, i) => (
        <div key={i} className="a2ui-field-error">
          {msg}
        </div>
      ))}
    </div>
  );
};
