/**
 * A2UI CheckBox component.
 *
 * Custom Notion-style checkbox with SVG check icon.
 * Writes to surface.dataModel via setAtPath. Evaluates checks for validation.
 */

import { useEffect, useRef, useState } from "react";
import { isDataBinding } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { evaluateChecks, resolveBoolean, resolveString, setAtPath } from "../data-binding";

export const A2UICheckBox: A2UIComponentRenderer = ({ component, surface }) => {
  const label = resolveString(component.label, surface);
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const required = component.required ? resolveBoolean(component.required, surface) : false;

  const bindingPath = isDataBinding(component.checked)
    ? (component.checked as { path: string }).path
    : null;

  const [checked, setChecked] = useState(() => {
    const initial = component.checked ? resolveBoolean(component.checked, surface) : false;
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
  const errors = touched ? evaluateChecks(checks, checked, surface) : [];

  const handleChange = () => {
    if (disabled) return;
    const newVal = !checked;
    setChecked(newVal);
    setTouched(true);
    if (bindingPath) setAtPath(surface.dataModel, bindingPath, newVal);
  };

  return (
    <div data-component-id={component.id} ref={wrapperRef}>
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
