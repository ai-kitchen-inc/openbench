/**
 * A2UI v0.10 data binding resolver.
 *
 * Resolves DataBinding ({path: string}) and FunctionCall ({call: string})
 * objects against a surface's data model using JSON Pointer (RFC 6901).
 */

import { isDataBinding, isFunctionCall } from "../core/utils";
import type { A2UISurface } from "../types";

/**
 * Resolve a potentially dynamic value against a surface's data model.
 *
 * - Static values pass through unchanged.
 * - DataBinding ({path: "/foo/bar"}) resolves via JSON Pointer.
 * - FunctionCall ({call: "formatString", args: {...}}) invokes a built-in function.
 */
export function resolveValue(value: unknown, surface: A2UISurface): unknown {
  if (isDataBinding(value)) {
    return resolvePointer(surface.dataModel, value.path);
  }
  if (isFunctionCall(value)) {
    return executeFunctionCall(value.call, value.args ?? {}, surface);
  }
  return value;
}

/**
 * Resolve a value and coerce to string.
 */
export function resolveString(value: unknown, surface: A2UISurface): string {
  const resolved = resolveValue(value, surface);
  return resolved != null ? String(resolved) : "";
}

/**
 * Resolve a value and coerce to number.
 */
export function resolveNumber(value: unknown, surface: A2UISurface): number {
  const resolved = resolveValue(value, surface);
  return typeof resolved === "number" ? resolved : Number(resolved) || 0;
}

/**
 * Resolve a value and coerce to boolean.
 */
export function resolveBoolean(value: unknown, surface: A2UISurface): boolean {
  const resolved = resolveValue(value, surface);
  return Boolean(resolved);
}

// ── JSON Pointer (RFC 6901) ──

/**
 * Resolve a JSON Pointer path against an object.
 * Returns undefined if the path doesn't exist.
 */
export function resolvePointer(obj: Record<string, unknown>, path: string): unknown {
  if (path === "/" || path === "") return obj;

  const segments = parsePointer(path);
  let current: unknown = obj;

  for (const seg of segments) {
    if (current == null || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[seg];
  }

  return current;
}

function parsePointer(path: string): string[] {
  if (!path.startsWith("/")) return [path];
  return path
    .substring(1)
    .split("/")
    .map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));
}

// ── JSON Pointer Write ──

/**
 * Set a value at a JSON Pointer path in an object.
 * Write counterpart to `resolvePointer`.
 */
export function setAtPath(obj: Record<string, unknown>, path: string, value: unknown): void {
  const segments = parsePointer(path);
  let current: Record<string, unknown> = obj;

  for (let i = 0; i < segments.length - 1; i++) {
    const seg = segments[i]!;
    if (!(seg in current) || typeof current[seg] !== "object" || current[seg] === null) {
      current[seg] = {};
    }
    current = current[seg] as Record<string, unknown>;
  }

  const lastSeg = segments[segments.length - 1]!;
  current[lastSeg] = value;
}

// ── Built-in A2UI Functions ──

type FnImpl = (args: Record<string, unknown>, surface: A2UISurface) => unknown;

const BUILTIN_FUNCTIONS: Record<string, FnImpl> = {
  // ── Validation functions ──
  required: (args) => {
    const value = args.value;
    return value != null && value !== "";
  },

  regex: (args) => {
    const value = String(args.value ?? "");
    const pattern = String(args.pattern ?? "");
    try {
      return new RegExp(pattern).test(value);
    } catch {
      return false;
    }
  },

  length: (args) => {
    const value = String(args.value ?? "");
    const min = typeof args.min === "number" ? args.min : 0;
    const max = typeof args.max === "number" ? args.max : Number.POSITIVE_INFINITY;
    return value.length >= min && value.length <= max;
  },

  numeric: (args) => {
    const value = args.value;
    const num = typeof value === "number" ? value : Number(value);
    if (Number.isNaN(num)) return false;
    if (typeof args.min === "number" && num < args.min) return false;
    if (typeof args.max === "number" && num > args.max) return false;
    return true;
  },

  email: (args) => {
    const value = String(args.value ?? "");
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  },

  // ── Format functions ──
  formatString: (args) => {
    let template = String(args.template ?? "");
    const values = (args.values ?? {}) as Record<string, unknown>;
    for (const [key, val] of Object.entries(values)) {
      template = template.replace(new RegExp(`\\{${key}\\}`, "g"), String(val));
    }
    return template;
  },

  formatNumber: (args) => {
    const value = Number(args.value ?? 0);
    const locale = String(args.locale ?? "en-US");
    const options = (args.options ?? {}) as Intl.NumberFormatOptions;
    return new Intl.NumberFormat(locale, options).format(value);
  },

  formatCurrency: (args) => {
    const value = Number(args.value ?? 0);
    const currency = String(args.currency ?? "USD");
    const locale = String(args.locale ?? "en-US");
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
    }).format(value);
  },

  formatDate: (args) => {
    const value = args.value;
    const locale = String(args.locale ?? "en-US");
    const options = (args.options ?? {}) as Intl.DateTimeFormatOptions;
    const date = value instanceof Date ? value : new Date(String(value));
    return new Intl.DateTimeFormat(locale, options).format(date);
  },

  pluralize: (args) => {
    const count = Number(args.count ?? 0);
    const singular = String(args.singular ?? "");
    const plural = String(args.plural ?? `${singular}s`);
    return count === 1 ? singular : plural;
  },

  // ── Action functions ──
  openUrl: (args) => {
    const url = String(args.url ?? "");
    if (url && typeof window !== "undefined") {
      window.open(url, "_blank", "noopener,noreferrer");
    }
    return url;
  },

  // ── Logic functions ──
  and: (args) => {
    const conditions = args.conditions;
    if (!Array.isArray(conditions)) return false;
    return conditions.every(Boolean);
  },

  or: (args) => {
    const conditions = args.conditions;
    if (!Array.isArray(conditions)) return false;
    return conditions.some(Boolean);
  },

  not: (args) => {
    return !args.value;
  },
};

/**
 * Deeply resolve all data bindings and function calls within a value.
 * Objects are traversed recursively; arrays are mapped.
 */
function deepResolve(value: unknown, surface: A2UISurface): unknown {
  if (isDataBinding(value)) {
    return resolvePointer(surface.dataModel, value.path);
  }
  if (isFunctionCall(value)) {
    return executeFunctionCall(value.call, value.args ?? {}, surface);
  }
  if (Array.isArray(value)) {
    return value.map((item) => deepResolve(item, surface));
  }
  if (typeof value === "object" && value !== null) {
    const resolved: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      resolved[k] = deepResolve(v, surface);
    }
    return resolved;
  }
  return value;
}

function executeFunctionCall(
  name: string,
  args: Record<string, unknown>,
  surface: A2UISurface,
): unknown {
  // Deep-resolve all data bindings in the function arguments
  const resolvedArgs: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(args)) {
    resolvedArgs[key] = deepResolve(val, surface);
  }

  const fn = BUILTIN_FUNCTIONS[name];
  if (!fn) {
    console.warn(`[A2UI] Unknown function: ${name}`);
    return undefined;
  }

  return fn(resolvedArgs, surface);
}

// ── Checks Evaluation ──

interface CheckDef {
  condition: unknown;
  message: string;
}

/**
 * Evaluate A2UI check rules against the current field value.
 *
 * Each check has a condition (FunctionCall) and a message.
 * Data bindings in condition args are replaced with `currentValue`
 * so validation runs against the live input, not stale dataModel.
 *
 * Returns an array of error messages for failed checks.
 */
export function evaluateChecks(
  checks: unknown[],
  currentValue: unknown,
  surface: A2UISurface,
): string[] {
  if (!Array.isArray(checks) || checks.length === 0) return [];

  const errors: string[] = [];
  const dummySurface: A2UISurface = { ...surface };

  for (const raw of checks) {
    const check = raw as CheckDef;
    if (!check?.condition || !check?.message) continue;

    const cond = check.condition as { call?: string; args?: Record<string, unknown> };
    if (!cond?.call) continue;

    // Substitute data bindings in args with the current value
    const resolvedArgs: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(cond.args ?? {})) {
      resolvedArgs[k] = isDataBinding(v) ? currentValue : v;
    }

    const fn = BUILTIN_FUNCTIONS[cond.call];
    if (fn && !fn(resolvedArgs, dummySurface)) {
      errors.push(check.message);
    }
  }

  return errors;
}
