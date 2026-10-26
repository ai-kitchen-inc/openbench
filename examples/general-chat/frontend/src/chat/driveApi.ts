/** Client for the per-user Google Drive OAuth endpoints (/auth/drive/*). */
import { apiFetch, apiPath } from "../api";
import { parseJsonResponse } from "./uploads";

export type DriveStatus = {
  configured: boolean;
  connected: boolean;
  email?: string | null;
};

export async function fetchDriveStatus(): Promise<DriveStatus> {
  const response = await apiFetch(apiPath("/auth/drive/status"));
  return parseJsonResponse<DriveStatus>(response);
}

export async function connectDrive(): Promise<{ authorizeUrl: string }> {
  const response = await apiFetch(apiPath("/auth/drive/connect"), { method: "POST" });
  return parseJsonResponse<{ authorizeUrl: string }>(response);
}

export async function disconnectDrive(): Promise<{ disconnected: boolean }> {
  const response = await apiFetch(apiPath("/auth/drive/disconnect"), { method: "POST" });
  return parseJsonResponse<{ disconnected: boolean }>(response);
}
