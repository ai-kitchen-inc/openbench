/**
 * A2UI TextField component.
 *
 * Supports types: text, number, email, password, date, multiline/textarea.
 * Writes to surface.dataModel via setAtPath. Evaluates checks for validation.
 * Listens for `a2ui-validate` DOM event to show errors on form submit.
 */

import { useEffect, useRef, useState } from "react";
import { isDataBinding } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { evaluateChecks, resolveBoolean, resolveString, setAtPath } from "../data-binding";

export const A2UITextField: A2UIComponentRenderer = ({ component, surface }) => {
  const label = resolveString(component.label, surface);
  const placeholder = resolveString(component.placeholder ?? "", surface);
  const inputType = (component.inputType as string) ?? "text";
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

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    setValue(newValue);
    if (bindingPath) setAtPath(surface.dataModel, bindingPath, newValue);
  };

  const handleBlur = () => setTouched(true);

  const isMultiline = inputType === "multiline" || inputType === "textarea";
  const wrapperClass = `a2ui-textfield${hasError ? " a2ui-textfield--error" : ""}`;

  return (
    <div className={wrapperClass} data-component-id={component.id} ref={wrapperRef}>
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
          onBlur={handleBlur}
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
          onBlur={handleBlur}
        />
      )}
      {errors.map((msg, i) => (
        <div key={i} className="a2ui-field-error">
          {msg}
        </div>
      ))}
    </div>
  );
};
