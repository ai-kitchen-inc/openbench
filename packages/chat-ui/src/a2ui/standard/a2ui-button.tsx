/**
 * A2UI Button component.
 *
 * Dispatches an A2UIAction on click.
 */

import { nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString, resolveValue } from "../data-binding";

export const A2UIButton: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label ?? component.text, surface);
  const variant = (component.variant as string) ?? "primary";
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;

  const handleClick = () => {
    if (!onAction || disabled) return;

    const event = component.action as
      | { event?: { name?: string; context?: Record<string, unknown> } }
      | undefined;

    if (event?.event) {
      // Resolve context values (may contain data bindings)
      const rawContext = event.event.context ?? {};
      const resolvedContext: Record<string, unknown> = {};
      for (const [key, val] of Object.entries(rawContext)) {
        resolvedContext[key] = resolveValue(val, surface);
      }

      onAction({
        name: event.event.name ?? "click",
        surfaceId: surface.surfaceId,
        sourceComponentId: component.id,
        timestamp: nowISO(),
        context: resolvedContext,
      });
    }
  };

  return (
    <button
      className={`a2ui-button a2ui-button--${variant}`}
      data-component-id={component.id}
      disabled={disabled}
      onClick={handleClick}
      type="button"
    >
      {label}
    </button>
  );
};
