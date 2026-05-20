export type MCPServerStatus = "enabled" | "disabled" | "running" | "stopped" | "failed" | "unavailable";

export type MCPDiscoveredTool = {
  name: string;
  namespacedName: string;
  namespaced_name?: string;
  description: string;
  inputSchema: Record<string, unknown>;
  input_schema?: Record<string, unknown>;
  enabled: boolean;
  discoveredAt: string | null;
  discovered_at?: string | null;
};

export type RegisteredMCPServer = {
  id: string;
  name: string;
  title: string;
  transport: "stdio" | "streamable-http" | "sse" | string;
  enabled: boolean;
  status: MCPServerStatus | string;
  error: string | null;
  registeredAt: string;
  updatedAt: string;
  lastDiscoveredAt: string | null;
  tools: MCPDiscoveredTool[];
  toolsCount: number;
  enabledToolsCount: number;
  displayConfig: Record<string, unknown>;
  config?: Record<string, unknown>;
};

export type MCPRegistryPayload = {
  servers: RegisteredMCPServer[];
};

export type ImportMCPConfigPayload = {
  config: string;
};

export type ToggleServerPayload = {
  enabled: boolean;
};

export type ToggleToolPayload = {
  enabled: boolean;
};
