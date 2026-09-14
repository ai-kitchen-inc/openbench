import { apiFetch, apiPath } from "../api";
import type { CustomSkill } from "./types";

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

export async function listCustomSkills(): Promise<CustomSkill[]> {
  const response = await apiFetch(apiPath("/admin/custom-skills"));
  const payload = await parseJsonResponse<{ skills: CustomSkill[] }>(response);
  return payload.skills ?? [];
}

export async function saveCustomSkill(payload: {
  id: string;
  name: string;
  description: string;
  triggers: string[];
  instructions: string;
  version: string;
}): Promise<CustomSkill> {
  const response = await apiFetch(apiPath("/admin/custom-skills"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse<CustomSkill>(response);
}

export async function deleteCustomSkill(id: string): Promise<void> {
  const response = await apiFetch(apiPath(`/admin/custom-skills/${encodeURIComponent(id)}`), {
    method: "DELETE",
  });
  await parseJsonResponse<{ ok: boolean }>(response);
}
