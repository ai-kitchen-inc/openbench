import { apiFetch, apiPath, type Role } from "../api";
import { parseJsonResponse } from "./sourcesApi";

export type UserItem = {
  username: string;
  role: Role;
  builtin: boolean;
  createdAt: string | null;
};

export async function listUsers(): Promise<UserItem[]> {
  const response = await apiFetch(apiPath("/controlled/users"));
  return parseJsonResponse<UserItem[]>(response);
}

export async function addUser(username: string, password: string, role: Role): Promise<UserItem> {
  const response = await apiFetch(apiPath("/controlled/users"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, role }),
  });
  return parseJsonResponse<UserItem>(response);
}

export async function deleteUser(username: string): Promise<void> {
  const response = await apiFetch(
    apiPath(`/controlled/users/${encodeURIComponent(username)}`),
    { method: "DELETE" },
  );
  await parseJsonResponse<{ ok: boolean }>(response);
}
