import type {
  ImportMCPConfigPayload,
  MCPRegistryPayload,
  RegisteredMCPServer,
  ToggleServerPayload,
  ToggleToolPayload,
} from "./types";

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let payload: Record<string, unknown> = {};
  if (text) {
    try {
      payload = JSON.parse(text) as Record<string, unknown>;
    } catch {
      if (!response.ok) throw new Error(text.trim() || "Request failed");
      throw new Error("Server returned an invalid JSON response.");
    }
  }
  if (!response.ok) {
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : typeof payload.error === "string"
          ? payload.error
          : `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }
  return payload as T;
}

export async function listServers(): Promise<MCPRegistryPayload> {
  return parseJsonResponse<MCPRegistryPayload>(await fetch("/mcp/catalogs"));
}

export async function importMCPConfig(payload: ImportMCPConfigPayload): Promise<MCPRegistryPayload> {
  return parseJsonResponse<MCPRegistryPayload>(
    await fetch("/mcp/catalogs/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function getServer(serverId: string): Promise<RegisteredMCPServer> {
  return parseJsonResponse<RegisteredMCPServer>(
    await fetch(`/mcp/catalogs/servers/${encodeURIComponent(serverId)}`),
  );
}

export async function discoverServer(
  serverId: string,
): Promise<{ server: RegisteredMCPServer; reload?: { error?: string | null } }> {
  return parseJsonResponse<{ server: RegisteredMCPServer; reload?: { error?: string | null } }>(
    await fetch(`/mcp/catalogs/servers/${encodeURIComponent(serverId)}/discover`, {
      method: "POST",
    }),
  );
}

export async function removeServer(serverId: string): Promise<{ ok: boolean }> {
  return parseJsonResponse<{ ok: boolean }>(
    await fetch(`/mcp/catalogs/servers/${encodeURIComponent(serverId)}`, {
      method: "DELETE",
    }),
  );
}

export async function toggleServer(
  serverId: string,
  payload: ToggleServerPayload,
): Promise<{ server: RegisteredMCPServer; reload?: { error?: string | null } }> {
  return parseJsonResponse<{ server: RegisteredMCPServer; reload?: { error?: string | null } }>(
    await fetch(`/mcp/catalogs/servers/${encodeURIComponent(serverId)}/enable`, {
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
    await fetch(
      `/mcp/catalogs/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}/enable`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  );
}
