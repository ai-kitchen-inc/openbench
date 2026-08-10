import { apiFetch, apiPath } from "../api";
import type { CustomFunction, FunctionRunResult } from "./types";

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let payload: Record<string, unknown> = {};
  if (text) {
    try {
      payload = JSON.parse(text) as Record<string, unknown>;
    } catch {
      if (!response.ok) throw new Error(text.trim() || "Request failed");
      throw new Error("Server returned an invalid JSON response.");
    }
  }
  if (!response.ok) {
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : typeof payload.error === "string"
          ? payload.error
          : `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }
  return payload as T;
}

export async function listFunctions(): Promise<CustomFunction[]> {
  const response = await apiFetch(apiPath("/functions"));
  const payload = await parseJsonResponse<{ functions: CustomFunction[] }>(response);
  return payload.functions ?? [];
}

export async function saveFunction(
  name: string,
  code: string,
  description: string,
): Promise<{ name: string }> {
  const response = await apiFetch(apiPath("/functions"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, code, description }),
  });
  return parseJsonResponse<{ name: string }>(response);
}

export async function deleteFunction(name: string): Promise<void> {
  const response = await apiFetch(apiPath(`/functions/${encodeURIComponent(name)}`), {
    method: "DELETE",
  });
  await parseJsonResponse<{ ok: boolean }>(response);
}

export async function runFunction(
  name: string,
  kwargs: Record<string, unknown>,
): Promise<FunctionRunResult> {
  const response = await apiFetch(apiPath(`/functions/${encodeURIComponent(name)}/run`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kwargs }),
  });
  return parseJsonResponse<FunctionRunResult>(response);
}
