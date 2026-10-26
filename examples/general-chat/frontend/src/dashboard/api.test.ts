import {
  deployDashboardToGrafana,
  exportDashboardToGrafana,
  listLiveDashboards,
  patchLiveDashboard,
  publicDashboardUrl,
  publishLiveDashboard,
} from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("live dashboard api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("lists dashboards from the payload wrapper", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ dashboards: [{ id: "abcdef123456", title: "A" }] })),
    );
    const items = await listLiveDashboards();
    expect(items.map((item) => item.id)).toEqual(["abcdef123456"]);
  });

  it("publishLiveDashboard PATCHes public=true and returns the live page url", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: "abcdef123456", public: true }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await publishLiveDashboard("abcdef123456");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/dashboard/live/abcdef123456");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ public: true });
    expect(result.url).toBe(publicDashboardUrl("abcdef123456"));
    expect(result.url.endsWith("/d/abcdef123456")).toBe(true);
  });

  it("patchLiveDashboard sends only the given fields", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: "abcdef123456", enabled: false }));
    vi.stubGlobal("fetch", fetchMock);
    await patchLiveDashboard("abcdef123456", { enabled: false });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ enabled: false });
  });

  it("export/deploy include dashboardId only when given", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ url: "https://g/d/x", panels: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await exportDashboardToGrafana({ title: "x" });
    await exportDashboardToGrafana({ title: "x" }, "abcdef123456");
    await deployDashboardToGrafana({ title: "x" }, "abcdef123456");
    const bodies = fetchMock.mock.calls.map((call) =>
      JSON.parse(String((call as unknown as [string, RequestInit])[1].body)),
    );
    expect(bodies[0]).toEqual({ viewModel: { title: "x" } });
    expect(bodies[1]).toEqual({ viewModel: { title: "x" }, dashboardId: "abcdef123456" });
    expect(bodies[2]).toEqual({ viewModel: { title: "x" }, dashboardId: "abcdef123456" });
    const [deployUrl] = fetchMock.mock.calls[2] as unknown as [string, RequestInit];
    expect(deployUrl).toBe("/dashboard/deploy/grafana");
  });

  it("wraps backend errors in Indonesian", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "Grafana unreachable" }, 503)));
    await expect(deployDashboardToGrafana({}, "abcdef123456")).rejects.toThrow(
      /Deploy gagal: .*Grafana unreachable/,
    );
  });
});
