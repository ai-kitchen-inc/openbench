import {
  apiFetch,
  apiPath,
  API_BASE_URL,
  LOCAL_ROLE_STORAGE_KEY,
  setAuthTokenProvider,
  setLocalRole,
} from "./api";

describe("apiPath", () => {
  afterEach(() => {
    setAuthTokenProvider(null);
    localStorage.removeItem(LOCAL_ROLE_STORAGE_KEY);
    vi.restoreAllMocks();
  });

  it("keeps same-origin paths when no backend URL is configured", () => {
    expect(API_BASE_URL).toBe("");
    expect(apiPath("/persona")).toBe("/persona");
    expect(apiPath("skills")).toBe("/skills");
  });

  it("does not rewrite absolute URLs", () => {
    expect(apiPath("https://api.example.com/health")).toBe("https://api.example.com/health");
  });

  it("leaves simple requests untouched without an auth token provider", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/persona");

    expect(fetchMock).toHaveBeenCalledWith("/persona");
  });

  it("attaches bearer tokens from the configured auth provider", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    setAuthTokenProvider(async () => "id-token");

    await apiFetch("/persona", { headers: { "Content-Type": "application/json" } });

    const [, init] = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer id-token");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("sends X-Local-Role when the local role override is stored", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    setLocalRole("user");

    await apiFetch("/account/me");

    const [, init] = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit];
    const headers = new Headers(init?.headers);
    expect(headers.get("X-Local-Role")).toBe("user");
  });

  it("omits X-Local-Role without a stored override", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/account/me");

    expect(fetchMock).toHaveBeenCalledWith("/account/me");
  });
});
