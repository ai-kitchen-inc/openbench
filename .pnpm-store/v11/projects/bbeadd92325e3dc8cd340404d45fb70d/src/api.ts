const rawApiBaseUrl = import.meta.env.VITE_BACKEND_URL?.trim() ?? "";

export const API_BASE_URL = rawApiBaseUrl.replace(/\/+$/, "");

type AuthTokenProvider = () => Promise<string | null>;

let authTokenProvider: AuthTokenProvider | null = null;

export function setAuthTokenProvider(provider: AuthTokenProvider | null): void {
  authTokenProvider = provider;
}

export async function authHeaders(): Promise<Record<string, string>> {
  if (!authTokenProvider) return {};
  const token = await authTokenProvider();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export const LOCAL_ROLE_STORAGE_KEY = "sss-local-role";

/** Local-dev role override ("view as user"); null = default admin.
 * The X-Local-Role header is ignored by the backend whenever real
 * (Firebase) auth is enabled, so carrying it is always safe. */
export function getLocalRole(): "user" | null {
  return localStorage.getItem(LOCAL_ROLE_STORAGE_KEY) === "user" ? "user" : null;
}

export function setLocalRole(role: "user" | null): void {
  if (role) localStorage.setItem(LOCAL_ROLE_STORAGE_KEY, role);
  else localStorage.removeItem(LOCAL_ROLE_STORAGE_KEY);
}

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const requestInit = init ?? {};
  const headers = new Headers(requestInit.headers);
  for (const [key, value] of Object.entries(await authHeaders())) {
    headers.set(key, value);
  }
  const localRole = getLocalRole();
  if (localRole) {
    headers.set("X-Local-Role", localRole);
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
