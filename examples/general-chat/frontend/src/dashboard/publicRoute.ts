/** Router-free match for the public live dashboard page: `/d/<id>`.
 * Ids are the 12-hex form shared with published snapshots. */

const PUBLIC_DASHBOARD_PATH_RE = /^\/d\/([0-9a-f]{12})\/?$/;

export type PublicDashboardRoute = { dashboardId: string };

export function matchPublicDashboardRoute(location: { pathname: string }): PublicDashboardRoute | null {
  const match = PUBLIC_DASHBOARD_PATH_RE.exec(location.pathname);
  return match ? { dashboardId: match[1] } : null;
}
