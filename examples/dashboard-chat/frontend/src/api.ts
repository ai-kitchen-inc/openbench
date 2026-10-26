const rawApiBaseUrl = import.meta.env.VITE_BACKEND_URL?.trim() ?? "";

export const API_BASE_URL = rawApiBaseUrl.replace(/\/+$/, "");

const TOKEN_STORAGE_KEY = "dashboard-chat-token";

export type Role = "admin" | "guest";

export interface AuthUser {
  username: string;
  role: Role;
}

export interface DbStatus {
  connected: boolean;
  dialect?: string;
  urlRedacted?: string;
  tableCount?: number | null;
}

export interface PanelSpec {
  id: string;
  type: "kpi" | "bar" | "line" | "area" | "pie" | "table";
  title: string;
  sql: string;
  width?: "third" | "half" | "twothirds" | "full";
  x?: string;
  /** Column(s) to plot. The agent sometimes emits a bare string. */
  y?: string[] | string;
  format?: "number" | "currency" | "percent";
  unit?: string;
}

export interface DashboardSpec {
  version: number;
  title: string;
  description?: string;
  updatedAt?: string;
  panels: PanelSpec[];
}

export interface PanelData {
  columns: string[];
  rows: (string | number | boolean | null)[][];
  truncated: boolean;
  elapsedMs: number;
}

// sessionStorage on purpose: a reload keeps you signed in, but closing
// the tab ends the session — no silent auto-login next time you visit.
export function getStoredToken(): string | null {
  try {
    return window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeToken(token: string | null): void {
  try {
    if (token) {
      window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // Storage unavailable (private mode) — session lives in memory only.
  }
}

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const requestInit = init ?? {};
  const headers = new Headers(requestInit.headers);
  for (const [key, value] of Object.entries(authHeaders())) {
    headers.set(key, value);
  }
  return fetch(input, { ...requestInit, headers });
}

export function apiPath(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (!API_BASE_URL) return normalizedPath;
  return `${API_BASE_URL}${normalizedPath}`;
}

async function readError(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => ({}))) as { detail?: string };
  return payload.detail ?? fallback;
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const response = await fetch(apiPath("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Login failed."));
  }
  const body = (await response.json()) as { token: string; username: string; role: Role };
  storeToken(body.token);
  return { username: body.username, role: body.role };
}

export async function logout(): Promise<void> {
  try {
    await apiFetch(apiPath("/auth/logout"), { method: "POST" });
  } catch {
    // Tokens are stateless — discarding the local copy is what matters.
  }
  storeToken(null);
}

/** Resolve the stored token to an account, or null when absent/expired. */
export async function fetchMe(): Promise<AuthUser | null> {
  if (!getStoredToken()) return null;
  const response = await apiFetch(apiPath("/auth/me"));
  if (!response.ok) {
    storeToken(null);
    return null;
  }
  return (await response.json()) as AuthUser;
}

export async function getDbStatus(): Promise<DbStatus> {
  const response = await apiFetch(apiPath("/db/status"));
  if (!response.ok) {
    throw new Error(await readError(response, "Could not read database status."));
  }
  return (await response.json()) as DbStatus;
}

export async function connectDb(url: string): Promise<{ dialect: string; tables: string[] }> {
  const response = await apiFetch(apiPath("/db/connect"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Could not connect to the database."));
  }
  return (await response.json()) as { dialect: string; tables: string[] };
}

export async function disconnectDb(): Promise<void> {
  await apiFetch(apiPath("/db/connection"), { method: "DELETE" });
}

/** Current dashboard spec, or null when none has been generated yet. */
export async function getDashboard(): Promise<DashboardSpec | null> {
  const response = await apiFetch(apiPath("/dashboard"));
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(await readError(response, "Could not load the dashboard."));
  }
  return (await response.json()) as DashboardSpec;
}

export async function getPanelData(panelId: string, signal?: AbortSignal): Promise<PanelData> {
  const response = await apiFetch(
    apiPath(`/dashboard/panels/${encodeURIComponent(panelId)}/data`),
    { signal },
  );
  if (!response.ok) {
    throw new Error(await readError(response, "Query failed."));
  }
  return (await response.json()) as PanelData;
}

/** Clear the user's single conversation (session + memory). */
export async function clearConversation(username: string): Promise<void> {
  await apiFetch(apiPath(`/sessions/user-${encodeURIComponent(username)}`), { method: "DELETE" });
}
