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
  source?: string;
  workloadName?: string | null;
  proxyUrl?: string | null;
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

export type ToolHiveStatus = {
  available: boolean;
  apiAvailable: boolean;
  cliAvailable: boolean;
  version: string | null;
  apiBaseUrl: string;
  source: string | null;
  error: string | null;
  setupHint: string | null;
  uiCliDetected?: boolean;
  cliPath?: string | null;
  managementMode?: "api" | "cli" | "ui-cli" | "unavailable" | string;
};

export type ToolHiveWorkload = {
  name: string;
  status: string;
  url: string | null;
  package: string | null;
  port: number | null;
  group: string | null;
  created: string | null;
  transport: string | null;
};

export type ToolHiveRegistryServer = {
  name: string;
  title: string;
  description: string | null;
  transport: string | null;
  tier: string | null;
  type: string | null;
  url: string | null;
  tools: string[];
};
