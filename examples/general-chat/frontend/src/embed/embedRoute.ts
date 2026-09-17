/** Router-free match for the standalone embed page: `/embed/<agentId>`.
 * The agent id follows the backend slug rule (`^[a-z0-9-]{1,64}$`). */

const EMBED_PATH_RE = /^\/embed\/([a-z0-9][a-z0-9-]{0,63})\/?$/;

export type EmbedRoute = {
  agentId: string;
  /** The agent's embed key from `?key=`; "" when absent. */
  embedKey: string;
  theme: "light" | "dark" | null;
};

export function matchEmbedRoute(location: {
  pathname: string;
  search: string;
}): EmbedRoute | null {
  const match = EMBED_PATH_RE.exec(location.pathname);
  if (!match) return null;
  const params = new URLSearchParams(location.search);
  const theme = params.get("theme");
  return {
    agentId: match[1],
    embedKey: (params.get("key") ?? "").trim(),
    theme: theme === "dark" || theme === "light" ? theme : null,
  };
}
