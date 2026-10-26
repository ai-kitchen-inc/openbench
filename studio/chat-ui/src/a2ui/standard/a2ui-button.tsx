/**
 * A2UI Button component.
 *
 * Dispatches an A2UIAction on click. Supports fullWidth for form submit.
 * Shows loading state during async action handling to prevent double-submit.
 * Validates sibling form fields before submitting (checks required, email, etc.).
 */

import { useState } from "react";
import { isDataBinding, nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import {
  evaluateChecks,
  resolveBoolean,
  resolvePointer,
  resolveString,
  resolveValue,
} from "../data-binding";

/**
 * Validate all components in the surface that have `checks`.
 * Returns an array of error messages from failing checks.
 */
function validateSurface(surface: {
  components: Map<string, Record<string, unknown>>;
  dataModel: Record<string, unknown>;
}): string[] {
  const allErrors: string[] = [];
  // Historical sessions persist a bare {surfaceId} without a components Map.
  // Guard so a click on such a surface never crashes (mirrors SurfaceRenderer).
  const components = surface?.components;
  if (!components || typeof components.values !== "function") return allErrors;
  for (const comp of components.values()) {
    const checks = comp.checks as unknown[];
    if (!Array.isArray(checks) || checks.length === 0) continue;

    // Determine the data-bound value property (value for most, checked for CheckBox)
    const valueProp = comp.checked ?? comp.value;
    if (!isDataBinding(valueProp)) continue;

    const bindingPath = (valueProp as { path: string }).path;
    const currentValue = resolvePointer(surface.dataModel, bindingPath);

    const errors = evaluateChecks(checks, currentValue, surface as any);
    allErrors.push(...errors);
  }
  return allErrors;
}

/**
 * Dispatch a custom DOM event on the surface element so input fields
 * can react (e.g., show validation errors by marking themselves as touched).
 */
function dispatchValidateEvent(surfaceId: string): void {
  if (typeof document === "undefined") return;
  const el = document.querySelector(`[data-surface-id="${surfaceId}"]`);
  if (el) {
    el.dispatchEvent(new CustomEvent("a2ui-validate", { bubbles: true }));
  }
}

export const A2UIButton: A2UIComponentRenderer = ({ component, surface, onAction }) => {
  const label = resolveString(component.label ?? component.text, surface);
  const variant = (component.variant as string) ?? "primary";
  const disabled = component.disabled ? resolveBoolean(component.disabled, surface) : false;
  const fullWidth = component.fullWidth ? resolveBoolean(component.fullWidth, surface) : false;

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (!onAction || disabled || isLoading) return;

    const event = component.action as
      | { event?: { name?: string; context?: Record<string, unknown> } }
      | undefined;

    if (event?.event) {
      // Clear previous error
      setError(null);

      // Validate all form fields in the surface before submitting
      const validationErrors = validateSurface(surface);
      if (validationErrors.length > 0) {
        // Trigger validation display on input fields
        dispatchValidateEvent(surface.surfaceId);
        setError(
          validationErrors.length === 1
            ? validationErrors[0]!
            : `${validationErrors.length} fields have errors`,
        );
        return;
      }

      // Resolve context values (may contain data bindings)
      const rawContext = event.event.context ?? {};
      const resolvedContext: Record<string, unknown> = {};
      for (const [key, val] of Object.entries(rawContext)) {
        resolvedContext[key] = resolveValue(val, surface);
      }

      setIsLoading(true);
      try {
        await onAction({
          name: event.event.name ?? "click",
          surfaceId: surface.surfaceId,
          sourceComponentId: component.id,
          timestamp: nowISO(),
          context: resolvedContext,
        });
      } catch (err) {
        // Show error inline instead of letting the form silently break
        const msg = err instanceof Error ? err.message : "Action failed";
        setError(msg);
      } finally {
        setIsLoading(false);
      }
    }
  };

  const classNames = [
    "a2ui-button",
    `a2ui-button--${variant}`,
    fullWidth ? "a2ui-button--full-width" : "",
    isLoading ? "a2ui-button--loading" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="a2ui-button-wrapper" data-component-id={component.id}>
      <button
        className={classNames}
        disabled={disabled || isLoading}
        onClick={handleClick}
        type="button"
      >
        {isLoading ? (
          <span className="a2ui-button__spinner" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle
                cx="8"
                cy="8"
                r="6"
                stroke="currentColor"
                strokeOpacity="0.25"
                strokeWidth="2"
              />
              <path
                d="M14 8a6 6 0 0 0-6-6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </span>
        ) : null}
        <span className={isLoading ? "a2ui-button__label--loading" : ""}>{label}</span>
      </button>
      {error && <div className="a2ui-button__error">{error}</div>}
    </div>
  );
};
