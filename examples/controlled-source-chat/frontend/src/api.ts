const rawApiBaseUrl = import.meta.env.VITE_BACKEND_URL?.trim() ?? "";

export const API_BASE_URL = rawApiBaseUrl.replace(/\/+$/, "");

const TOKEN_STORAGE_KEY = "controlled-chat-token";

export type Role = "admin" | "guest";

export interface AuthUser {
  username: string;
  role: Role;
}

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeToken(token: string | null): void {
  try {
    if (token) {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // Storage unavailable (private mode) — session lives in memory only.
  }
}

export async function authHeaders(): Promise<Record<string, string>> {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const requestInit = init ?? {};
  const headers = new Headers(requestInit.headers);
  for (const [key, value] of Object.entries(await authHeaders())) {
    headers.set(key, value);
  }
  if ([...headers.keys()].length === 0) {
    return init ? fetch(input, init) : fetch(input);
  }
  return fetch(input, { ...requestInit, headers });
}

export function apiPath(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (!API_BASE_URL) return normalizedPath;
  return `${API_BASE_URL}${normalizedPath}`;
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const response = await fetch(apiPath("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(payload.detail ?? "Login failed.");
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

/** Transcribe a recorded audio blob via the backend (mic voice-input fallback). */
export async function transcribeAudio(blob: Blob): Promise<string> {
  const form = new FormData();
  const ext = blob.type.includes("ogg") ? "ogg" : "webm";
  form.append("file", blob, `voice-input.${ext}`);
  const response = await apiFetch(apiPath("/chat/transcribe"), { method: "POST", body: form });
  if (!response.ok) {
    throw new Error(`Transcription request failed: ${response.status}`);
  }
  const data = (await response.json()) as { transcript?: string };
  return data.transcript ?? "";
}
