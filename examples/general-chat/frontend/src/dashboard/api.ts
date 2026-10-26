/** REST client for live (database-bound) dashboards: `/dashboard/live*` and
 * the Grafana export/deploy routes. Mirrors `functions/api.ts`. */
import { apiFetch, apiPath } from "../api";
import { parseJsonResponse, readErrorMessage } from "../shared/apiHelpers";

export type LiveDashboardSummary = {
  id: string;
  title: string;
  description: string;
  refreshIntervalSeconds: number;
  enabled: boolean;
  public: boolean;
  version: number;
  lastRefreshAt: string | null;
  lastError: string | null;
  nextRunAt: string | null;
  createdAt: string;
  updatedAt: string;
  rowCounts: Record<string, number>;
};

export type LiveDashboardPatch = {
  enabled?: boolean;
  public?: boolean;
  title?: string;
  refreshIntervalSeconds?: number;
};

const JSON_HEADERS = { "Content-Type": "application/json" };

function livePath(id: string, suffix = ""): string {
  return apiPath(`/dashboard/live/${encodeURIComponent(id)}${suffix}`);
}

export async function listLiveDashboards(): Promise<LiveDashboardSummary[]> {
  const response = await apiFetch(apiPath("/dashboard/live"));
  const payload = await parseJsonResponse<{ dashboards: LiveDashboardSummary[] }>(response);
  return payload.dashboards ?? [];
}

export async function patchLiveDashboard(
  id: string,
  patch: LiveDashboardPatch,
): Promise<LiveDashboardSummary> {
  const response = await apiFetch(livePath(id), {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(patch),
  });
  return parseJsonResponse<LiveDashboardSummary>(response);
}

export async function refreshLiveDashboard(id: string): Promise<void> {
  const response = await apiFetch(livePath(id, "/refresh"), { method: "POST" });
  await parseJsonResponse<unknown>(response);
}

export async function deleteLiveDashboard(id: string): Promise<void> {
  const response = await apiFetch(livePath(id), { method: "DELETE" });
  await parseJsonResponse<{ ok: boolean }>(response);
}

/** Shareable page of a public live dashboard (same origin as the SPA). */
export function publicDashboardUrl(id: string): string {
  return `${window.location.origin}/d/${encodeURIComponent(id)}`;
}

/** "Publish" on a live frame: flip the record public and hand back its live page. */
export async function publishLiveDashboard(id: string): Promise<{ url: string }> {
  await patchLiveDashboard(id, { public: true });
  return { url: publicDashboardUrl(id) };
}

function dashboardBody(viewModel: unknown, dashboardId?: string): string {
  return JSON.stringify(dashboardId ? { viewModel, dashboardId } : { viewModel });
}

/** Grafana JSON model; with `dashboardId` the panels run the record's own SQL. */
export async function exportDashboardToGrafana(
  viewModel: unknown,
  dashboardId?: string,
): Promise<Record<string, unknown>> {
  const response = await apiFetch(apiPath("/dashboard/export/grafana"), {
    method: "POST",
    headers: JSON_HEADERS,
    body: dashboardBody(viewModel, dashboardId),
  });
  try {
    return await parseJsonResponse<Record<string, unknown>>(response);
  } catch (error) {
    throw new Error(`Ekspor gagal: ${readErrorMessage(error)}`);
  }
}

/** Push to the hosted Grafana; live records deploy as self-refreshing SQL panels. */
export async function deployDashboardToGrafana(
  viewModel: unknown,
  dashboardId?: string,
): Promise<{ url: string }> {
  const response = await apiFetch(apiPath("/dashboard/deploy/grafana"), {
    method: "POST",
    headers: JSON_HEADERS,
    body: dashboardBody(viewModel, dashboardId),
  });
  try {
    return await parseJsonResponse<{ url: string }>(response);
  } catch (error) {
    throw new Error(`Deploy gagal: ${readErrorMessage(error)}`);
  }
}
