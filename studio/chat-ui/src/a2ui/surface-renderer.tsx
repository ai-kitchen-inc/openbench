/**
 * SurfaceRenderer — resolves an A2UI surface's component adjacency list
 * into a React component tree.
 *
 * Algorithm:
 * 1. Index all components by ID from surface.components Map.
 * 2. Find root component (id === "root").
 * 3. Recursively resolve each component:
 *    a. Look up renderer from catalog (standard → custom → user-registered).
 *    b. Resolve "children" property (array of component IDs) → recurse.
 *    c. Render the component with resolved props and children.
 * 4. Wire user actions to onAction callback.
 */

import type React from "react";
import type { A2UIAction, A2UIComponent, A2UISurface } from "../types";
import { resolveComponent } from "./catalog";

export interface SurfaceRendererProps {
  /** The A2UI surface to render. */
  surface: A2UISurface;
  /** Callback when a user action occurs (button click, form submit, etc.). */
  onAction?: (action: A2UIAction) => void | Promise<void>;
}

/**
 * Render an A2UI surface as a React component tree.
 */
export const SurfaceRenderer: React.FC<SurfaceRendererProps> = ({ surface, onAction }) => {
  // Historical sessions reloaded from the server persist only the
  // surfaceId (no components tree), and occasionally a message.surfaces
  // entry is a bare pointer until the stream fills it in. Guard against
  // both so a half-built record never crashes the chat panel.
  const components = surface?.components;
  if (!components || typeof components.get !== "function") {
    return null;
  }
  const root = components.get("root");
  if (!root) {
    return null;
  }

  return (
    <div className="a2ui-surface" data-surface-id={surface.surfaceId}>
      <ComponentNode component={root} surface={surface} onAction={onAction} />
    </div>
  );
};

// ── Internal recursive renderer ──

interface ComponentNodeProps {
  component: A2UIComponent;
  surface: A2UISurface;
  onAction?: (action: A2UIAction) => void | Promise<void>;
}

const ComponentNode: React.FC<ComponentNodeProps> = ({ component, surface, onAction }) => {
  const Renderer = resolveComponent(component.component);

  if (!Renderer) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(
        `[SurfaceRenderer] Unknown component type: "${component.component}" (id: ${component.id})`,
      );
    }
    return null;
  }

  // Resolve children: "children" property is an array of component IDs
  const childIds = component.children as string[] | undefined;
  let children: React.ReactNode = null;

  if (Array.isArray(childIds) && childIds.length > 0) {
    children = childIds.map((childId) => {
      const childComponent = surface.components.get(childId);
      if (!childComponent) {
        if (process.env.NODE_ENV !== "production") {
          console.warn(
            `[SurfaceRenderer] Child component not found: "${childId}" (parent: ${component.id})`,
          );
        }
        return null;
      }
      return (
        <ComponentNode
          key={childId}
          component={childComponent}
          surface={surface}
          onAction={onAction}
        />
      );
    });
  }

  return (
    <Renderer component={component} surface={surface} onAction={onAction}>
      {children}
    </Renderer>
  );
};
