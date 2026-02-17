/**
 * A2UI Slider component.
 *
 * Custom styled range slider with value badge.
 * Writes to surface.dataModel via setAtPath. Evaluates checks for validation.
 */

import { useEffect, useRef, useState } from "react";
import { isDataBinding } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import {
  evaluateChecks,
  resolveBoolean,
  resolveNumber,
  resolveString,
  setAtPath,
} from "../data-binding";

export const A2UISlider: A2UIComponentRenderer = ({ component, surface }) => {
  const label = resolveString(component.label ?? "", surface);
  const min = resolveNumber(component.min ?? 0, surface);
  const max = resolveNumber(component.max ?? 100, surface);
  const step = resolveNumber(component.step ?? 1, surface);
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const required = component.required ? resolveBoolean(component.required, surface) : false;

  const bindingPath = isDataBinding(component.value)
    ? (component.value as { path: string }).path
    : null;

  const [value, setValue] = useState(() => {
    const initial = resolveNumber(component.value ?? min, surface);
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

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newVal = Number(e.target.value);
    setValue(newVal);
    setTouched(true);
    if (bindingPath) setAtPath(surface.dataModel, bindingPath, newVal);
  };

  // Calculate fill percentage for track styling
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;

  return (
    <div className="a2ui-slider" data-component-id={component.id} ref={wrapperRef}>
      {label && (
        <div className="a2ui-slider__header">
          <label className="a2ui-slider__label">
            {label}
            {required && <span className="a2ui-field-required"> *</span>}
          </label>
          <span className="a2ui-slider__badge">{value}</span>
        </div>
      )}
      <input
        className="a2ui-slider__input"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={handleChange}
        style={{
          background: `linear-gradient(to right, #37352f ${pct}%, rgba(55,53,47,0.12) ${pct}%)`,
        }}
      />
      <div className="a2ui-slider__range">
        <span className="a2ui-slider__min">{min}</span>
        <span className="a2ui-slider__max">{max}</span>
      </div>
      {errors.map((msg, i) => (
        <div key={i} className="a2ui-field-error">
          {msg}
        </div>
      ))}
    </div>
  );
};
