/**
 * A2UI v0.10 JSONL message processor.
 *
 * Parses incoming A2UI messages and maintains per-surface state.
 * No React dependency -- pure state management.
 */

import { setAtPath } from "../a2ui/data-binding";
import type { A2UIComponent, A2UISurface } from "../types";

const A2UI_VERSION = "v0.10";

export type SurfaceChangeListener = (surfaceId: string) => void;

export class A2UIMessageProcessor {
  private surfaces: Map<string, A2UISurface> = new Map();
  private listeners: Set<SurfaceChangeListener> = new Set();

  /**
   * Process a single parsed A2UI message.
   * Call this for each message received from the transport.
   */
  processMessage(data: Record<string, unknown>): void {
    // Validate version
    if (data.version !== A2UI_VERSION) {
      // Not an A2UI message (could be stream envelope), skip
      return;
    }

    if ("createSurface" in data) {
      this.handleCreateSurface(data.createSurface as Record<string, unknown>);
    } else if ("updateComponents" in data) {
      this.handleUpdateComponents(data.updateComponents as Record<string, unknown>);
    } else if ("updateDataModel" in data) {
      this.handleUpdateDataModel(data.updateDataModel as Record<string, unknown>);
    } else if ("deleteSurface" in data) {
      this.handleDeleteSurface(data.deleteSurface as Record<string, unknown>);
    }
  }

  /** Get a surface by ID. */
  getSurface(surfaceId: string): A2UISurface | undefined {
    return this.surfaces.get(surfaceId);
  }

  /** Get all surfaces that have a root component (renderable).
   *  Returns shallow clones so React detects prop changes after in-place mutations.
   */
  getRenderableSurfaces(): A2UISurface[] {
    const result: A2UISurface[] = [];
    for (const surface of this.surfaces.values()) {
      if (surface.components.has("root")) {
        result.push({ ...surface, components: new Map(surface.components) });
      }
    }
    return result;
  }

  /** Get all surface IDs. */
  getSurfaceIds(): string[] {
    return Array.from(this.surfaces.keys());
  }

  /** Register a listener for surface changes. */
  onChange(listener: SurfaceChangeListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Clear all surfaces (keeps listeners intact). */
  reset(): void {
    this.surfaces.clear();
  }

  // ── Internal handlers ──

  private handleCreateSurface(payload: Record<string, unknown>): void {
    const surfaceId = payload.surfaceId as string;
    const catalogId = payload.catalogId as string;
    const theme = payload.theme as A2UISurface["theme"];
    const sendDataModel = payload.sendDataModel as boolean | undefined;

    this.surfaces.set(surfaceId, {
      surfaceId,
      catalogId,
      components: new Map(),
      dataModel: {},
      theme,
      sendDataModel,
    });

    this.notify(surfaceId);
  }

  private handleUpdateComponents(payload: Record<string, unknown>): void {
    const surfaceId = payload.surfaceId as string;
    const surface = this.surfaces.get(surfaceId);
    if (!surface) {
      console.warn(`[A2UIMessageProcessor] updateComponents for unknown surface: ${surfaceId}`);
      return;
    }

    const components = payload.components as A2UIComponent[];

    // If the update contains a new root, do a full replacement (clear old components)
    // so orphaned form fields don't linger in the Map
    const hasNewRoot = components.some((c) => c.id === "root");
    if (hasNewRoot) {
      surface.components.clear();
    }

    for (const comp of components) {
      surface.components.set(comp.id, comp);
    }

    this.notify(surfaceId);
  }

  private handleUpdateDataModel(payload: Record<string, unknown>): void {
    const surfaceId = payload.surfaceId as string;
    const surface = this.surfaces.get(surfaceId);
    if (!surface) {
      console.warn(`[A2UIMessageProcessor] updateDataModel for unknown surface: ${surfaceId}`);
      return;
    }

    const path = (payload.path as string | undefined) ?? "/";
    const value = payload.value;

    if (path === "/") {
      // Replace entire data model
      if (value !== undefined) {
        surface.dataModel = value as Record<string, unknown>;
      } else {
        surface.dataModel = {};
      }
    } else {
      // Set value at JSON Pointer path
      if (value !== undefined) {
        setAtPath(surface.dataModel, path, value);
      } else {
        removeAtPath(surface.dataModel, path);
      }
    }

    this.notify(surfaceId);
  }

  private handleDeleteSurface(payload: Record<string, unknown>): void {
    const surfaceId = payload.surfaceId as string;
    this.surfaces.delete(surfaceId);
    this.notify(surfaceId);
  }

  private notify(surfaceId: string): void {
    for (const listener of this.listeners) {
      listener(surfaceId);
    }
  }
}

// ── JSON Pointer helpers (RFC 6901) ──

/**
 * Parse a JSON Pointer path into segments.
 * "/foo/bar/0" -> ["foo", "bar", "0"]
 */
function parsePointer(path: string): string[] {
  if (!path.startsWith("/")) return [path];
  return path
    .substring(1)
    .split("/")
    .map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));
}

/**
 * Remove a value at a JSON Pointer path from an object.
 */
function removeAtPath(obj: Record<string, unknown>, path: string): void {
  const segments = parsePointer(path);
  let current: Record<string, unknown> = obj;

  for (let i = 0; i < segments.length - 1; i++) {
    const seg = segments[i]!;
    if (!(seg in current) || typeof current[seg] !== "object") {
      return; // Path doesn't exist, nothing to remove
    }
    current = current[seg] as Record<string, unknown>;
  }

  const lastSeg = segments[segments.length - 1]!;
  delete current[lastSeg];
}
