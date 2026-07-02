import type { RegisteredMCPServer } from "./types";

export type StatusFilter = "all" | "enabled" | "disabled" | "failed";
export type SortMode = "name" | "status" | "tools";

export type RegistryFilters = {
  query: string;
  status: StatusFilter;
  sort: SortMode;
};

export function filterServers(
  servers: RegisteredMCPServer[],
  filters: RegistryFilters,
): RegisteredMCPServer[] {
  const query = filters.query.trim().toLowerCase();
  const result = servers.filter((server) => {
    const toolText = server.tools.map((tool) => `${tool.name} ${tool.description}`).join(" ");
    const provider = server.providerKind ?? server.provider_kind ?? server.sourceType ?? server.source_type ?? server.source ?? "";
    const haystack = [server.name, server.title, provider, server.transport, server.status, toolText]
      .join(" ")
      .toLowerCase();
    if (query && !haystack.includes(query)) return false;
    if (filters.status === "enabled" && !server.enabled) return false;
    if (filters.status === "disabled" && server.enabled) return false;
    if (filters.status === "failed" && server.status !== "failed") return false;
    return true;
  });

  return result.sort((a, b) => {
    if (filters.sort === "status") return String(a.status).localeCompare(String(b.status));
    if (filters.sort === "tools") return b.toolsCount - a.toolsCount;
    return a.name.localeCompare(b.name);
  });
}
