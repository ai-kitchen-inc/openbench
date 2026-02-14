/**
 * A2UI Slider component.
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

  return (
    <div className="a2ui-slider" data-component-id={component.id}>
      {label && (
        <label className="a2ui-slider__label">
          {label}: {value}
        </label>
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
      />
    </div>
  );
};
