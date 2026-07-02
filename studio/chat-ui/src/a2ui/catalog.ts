/**
 * A2UI component catalog — maps component type strings to React renderers.
 *
 * Standard catalog (A2UI v0.10 spec): 18 components.
 * Custom catalog (OpenBench): ObChart, ObDashboardFrame, ObFileCard,
 * ObCodeBlock, ObMarkdown, ObTable, ObCallout.
 *
 * Use `registerCustomComponent()` to add your own.
 */

import type { A2UIComponentRenderer, ComponentCatalog } from "../types";

import { CUSTOM_CATALOG } from "./custom";
// Lazy-loaded standard catalog
import { STANDARD_CATALOG } from "./standard";

/** Merged catalog: standard + custom + user-registered. */
const userCatalog: ComponentCatalog = {};

/**
 * Register a custom component renderer for a given type string.
 *
 * ```ts
 * registerCustomComponent('MyWidget', MyWidgetComponent);
 * ```
 */
export function registerCustomComponent(type: string, renderer: A2UIComponentRenderer): void {
  userCatalog[type] = renderer;
}

/**
 * Look up a renderer for a component type string.
 * Resolution order: user → custom → standard.
 */
export function resolveComponent(type: string): A2UIComponentRenderer | undefined {
  return userCatalog[type] ?? CUSTOM_CATALOG[type] ?? STANDARD_CATALOG[type];
}

/**
 * Get the full merged component catalog.
 */
export function getComponentCatalog(): ComponentCatalog {
  return {
    ...STANDARD_CATALOG,
    ...CUSTOM_CATALOG,
    ...userCatalog,
  };
}

/**
 * Check if a component type is known (registered in any catalog).
 */
export function isKnownComponent(type: string): boolean {
  return resolveComponent(type) !== undefined;
}
