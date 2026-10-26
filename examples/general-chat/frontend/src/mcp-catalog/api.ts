import type {
  ImportMCPConfigPayload,
  MCPRegistryPayload,
  RegisteredMCPServer,
  ToggleServerPayload,
  ToggleToolPayload,
  ToolHiveRegistryServer,
  ToolHiveStatus,
  ToolHiveWorkload,
} from "./types";
import { apiFetch, apiPath } from "../api";
import { parseJsonResponse } from "../shared/apiHelpers";

export async function listServers(): Promise<MCPRegistryPayload> {
  return parseJsonResponse<MCPRegistryPayload>(await apiFetch(apiPath("/mcp/catalogs")));
}

export async function importMCPConfig(payload: ImportMCPConfigPayload): Promise<MCPRegistryPayload> {
  return parseJsonResponse<MCPRegistryPayload>(
    await apiFetch(apiPath("/mcp/catalogs/import"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function getServer(serverId: string): Promise<RegisteredMCPServer> {
  return parseJsonResponse<RegisteredMCPServer>(
    await apiFetch(apiPath(`/mcp/catalogs/servers/${encodeURIComponent(serverId)}`)),
  );
}

export async function discoverServer(
  serverId: string,
): Promise<{ server: RegisteredMCPServer; reload?: { error?: string | null } }> {
  return parseJsonResponse<{ server: RegisteredMCPServer; reload?: { error?: string | null } }>(
    await apiFetch(apiPath(`/mcp/catalogs/servers/${encodeURIComponent(serverId)}/discover`), {
      method: "POST",
    }),
  );
}

export async function removeServer(serverId: string): Promise<{ ok: boolean }> {
  return parseJsonResponse<{ ok: boolean }>(
    await apiFetch(apiPath(`/mcp/catalogs/servers/${encodeURIComponent(serverId)}`), {
      method: "DELETE",
    }),
  );
}

export async function toggleServer(
  serverId: string,
  payload: ToggleServerPayload,
): Promise<{ server: RegisteredMCPServer; reload?: { error?: string | null } }> {
  return parseJsonResponse<{ server: RegisteredMCPServer; reload?: { error?: string | null } }>(
    await apiFetch(apiPath(`/mcp/catalogs/servers/${encodeURIComponent(serverId)}/enable`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function toggleTool(
  serverId: string,
  toolName: string,
  payload: ToggleToolPayload,
): Promise<{ server: RegisteredMCPServer; reload?: { error?: string | null } }> {
  return parseJsonResponse<{ server: RegisteredMCPServer; reload?: { error?: string | null } }>(
    await apiFetch(
      apiPath(
        `/mcp/catalogs/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}/enable`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  );
}

export async function getToolHiveStatus(): Promise<ToolHiveStatus> {
  return parseJsonResponse<ToolHiveStatus>(await apiFetch(apiPath("/toolhive/status")));
}

export async function listToolHiveWorkloads(): Promise<{ workloads: ToolHiveWorkload[] }> {
  return parseJsonResponse<{ workloads: ToolHiveWorkload[] }>(
    await apiFetch(apiPath("/toolhive/workloads")),
  );
}

export async function listToolHiveRegistryServers(): Promise<{ servers: ToolHiveRegistryServer[] }> {
  return parseJsonResponse<{ servers: ToolHiveRegistryServer[] }>(
    await apiFetch(apiPath("/toolhive/registry/servers")),
  );
}

export async function startToolHiveWorkload(payload: {
  target: string;
  name?: string;
  allowRemote?: boolean;
}): Promise<{ workload: ToolHiveWorkload }> {
  return parseJsonResponse<{ workload: ToolHiveWorkload }>(
    await apiFetch(apiPath("/toolhive/workloads"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function stopToolHiveWorkload(name: string): Promise<{ ok: boolean }> {
  return parseJsonResponse<{ ok: boolean }>(
    await apiFetch(apiPath(`/toolhive/workloads/${encodeURIComponent(name)}/stop`), {
      method: "POST",
    }),
  );
}

export async function restartToolHiveWorkload(name: string): Promise<{ ok: boolean }> {
  return parseJsonResponse<{ ok: boolean }>(
    await apiFetch(apiPath(`/toolhive/workloads/${encodeURIComponent(name)}/restart`), {
      method: "POST",
    }),
  );
}

export async function deleteToolHiveWorkload(name: string): Promise<{ ok: boolean }> {
  return parseJsonResponse<{ ok: boolean }>(
    await apiFetch(apiPath(`/toolhive/workloads/${encodeURIComponent(name)}`), {
      method: "DELETE",
    }),
  );
}

export async function importRunningToolHiveWorkloads(
  names: string[],
): Promise<MCPRegistryPayload & { reload?: { error?: string | null } }> {
  return parseJsonResponse<MCPRegistryPayload & { reload?: { error?: string | null } }>(
    await apiFetch(apiPath("/mcp/catalogs/toolhive/import-running"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names }),
    }),
  );
}
