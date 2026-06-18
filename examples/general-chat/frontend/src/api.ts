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
