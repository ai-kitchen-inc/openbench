/**
 * A2UI Slider component.
 *
 * Custom styled range slider with value badge.
 */

import { useState } from "react";
import { nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveNumber, resolveString } from "../data-binding";

export const A2UISlider: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label ?? "", surface);
  const min = resolveNumber(component.min ?? 0, surface);
  const max = resolveNumber(component.max ?? 100, surface);
  const step = resolveNumber(component.step ?? 1, surface);
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const required = component.required ? resolveBoolean(component.required, surface) : false;
  const initialValue = resolveNumber(component.value ?? min, surface);

  const [value, setValue] = useState(initialValue);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newVal = Number(e.target.value);
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

  // Calculate fill percentage for track styling
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;

  return (
    <div className="a2ui-slider" data-component-id={component.id}>
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
    </div>
  );
};
