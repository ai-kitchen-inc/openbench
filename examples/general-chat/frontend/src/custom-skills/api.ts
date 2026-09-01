import { apiFetch, apiPath } from "../api";
import { parseJsonResponse } from "../shared/apiHelpers";
import type { CustomSkill } from "./types";

export async function listCustomSkills(): Promise<CustomSkill[]> {
  const response = await apiFetch(apiPath("/admin/custom-skills"));
  const payload = await parseJsonResponse<{ skills: CustomSkill[] }>(response);
  return payload.skills ?? [];
}

async function postCustomSkill(payload: Record<string, unknown>): Promise<CustomSkill> {
  const response = await apiFetch(apiPath("/admin/custom-skills"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse<CustomSkill>(response);
}

export async function createCustomSkillFromPrompt(prompt: string): Promise<CustomSkill> {
  return postCustomSkill({ prompt });
}

export async function saveCustomSkillMarkdown(id: string, skillMd: string): Promise<CustomSkill> {
  return postCustomSkill({ id, skill_md: skillMd });
}

export async function deleteCustomSkill(id: string): Promise<void> {
  const response = await apiFetch(apiPath(`/admin/custom-skills/${encodeURIComponent(id)}`), {
    method: "DELETE",
  });
  await parseJsonResponse<{ ok: boolean }>(response);
}
