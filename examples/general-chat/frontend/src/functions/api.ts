import { apiFetch, apiPath } from "../api";
import { parseJsonResponse } from "../shared/apiHelpers";
import type { CustomFunction, FunctionRunResult } from "./types";

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
