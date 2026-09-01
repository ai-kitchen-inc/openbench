/** Typed clients for the account + admin REST API (Firebase-token auth via
 * src/api.ts). All error `detail` strings coming from the backend are already
 * in Bahasa Indonesia and are surfaced verbatim. */
import { apiFetch, apiPath, authHeaders } from "../api";
import { parseJsonResponse, readErrorMessage, xhrUpload } from "../shared/apiHelpers";

// ── Shared helpers (re-exported for existing importers) ──

export { parseJsonResponse, readErrorMessage };

// ── /account/me ──

export type Role = "admin" | "user";

export type Capabilities = {
  attachments: boolean;
  session_sources: boolean;
  mcp_management: boolean;
  custom_functions: boolean;
  dashboards: boolean;
  image_search: boolean;
  /** Optional: older backends omit it; treat absent as allowed. */
  agent_selection?: boolean;
};

export type Me = {
  email: string;
  role: Role;
  displayName: string;
  /** Workspace/team group id; empty when ungrouped. */
  group?: string;
  capabilities: Capabilities;
  global: { file_generation: boolean };
  /** True when the backend runs with auth disabled (local dev) — the UI
   * may then offer the local "view as user" role toggle. */
  authDisabled?: boolean;
};

/** Thrown when the signed-in Google account has not been granted access
 * (backend responds 403 on /account/me). */
export class AccessDeniedError extends Error {
  constructor(message = "Akun ini belum diberi akses.") {
    super(message);
    this.name = "AccessDeniedError";
  }
}

/** Resolve the signed-in account's profile. 403 → AccessDeniedError,
 * 401 → null (not authenticated), network/5xx → rethrown Error. */
export async function fetchMe(): Promise<Me | null> {
  const response = await apiFetch(apiPath("/account/me"));
  if (response.status === 401) return null;
  if (response.status === 403) {
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = typeof payload.detail === "string" ? payload.detail : "";
    } catch {
      // Non-JSON body — fall through to the default message.
    }
    throw new AccessDeniedError(detail || undefined);
  }
  return parseJsonResponse<Me>(response);
}

// ── /account/shared-sources (any authenticated user) ──

export type SharedSource = {
  id: string;
  sessionId: string;
  name: string;
  kind: string;
  mimeType: string;
  status: "ready" | "failed" | "processing";
  error: string | null;
  sizeBytes: number;
  createdAt: string;
  url: string | null;
  textPreview?: string;
  textTruncated?: boolean;
};

export async function listAccountSharedSources(): Promise<SharedSource[]> {
  const response = await apiFetch(apiPath("/account/shared-sources"));
  const payload = await parseJsonResponse<{ sources: SharedSource[] }>(response);
  return payload.sources ?? [];
}

/** Shared + group sources in one call (group slice is empty when the
 * requester has no group). */
export async function listAccountSources(): Promise<{
  sources: SharedSource[];
  groupSources: SharedSource[];
}> {
  const response = await apiFetch(apiPath("/account/shared-sources"));
  const payload = await parseJsonResponse<{
    sources: SharedSource[];
    groupSources?: SharedSource[];
  }>(response);
  return { sources: payload.sources ?? [], groupSources: payload.groupSources ?? [] };
}

// ── /admin/users ──

export type UserItem = {
  email: string;
  role: Role;
  displayName: string;
  createdAt: string | null;
  addedBy: string | null;
  group?: string;
};

export async function listUsers(): Promise<UserItem[]> {
  const response = await apiFetch(apiPath("/admin/users"));
  const payload = await parseJsonResponse<{ users: UserItem[] }>(response);
  return payload.users ?? [];
}

export async function addUser(
  email: string,
  role: Role,
  displayName?: string,
): Promise<UserItem> {
  const response = await apiFetch(apiPath("/admin/users"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(displayName ? { email, role, displayName } : { email, role }),
  });
  return parseJsonResponse<UserItem>(response);
}

export async function updateUser(
  email: string,
  patch: { role?: Role; displayName?: string; group?: string },
): Promise<UserItem> {
  const response = await apiFetch(apiPath(`/admin/users/${encodeURIComponent(email)}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJsonResponse<UserItem>(response);
}

export async function deleteUser(email: string): Promise<void> {
  const response = await apiFetch(apiPath(`/admin/users/${encodeURIComponent(email)}`), {
    method: "DELETE",
  });
  await parseJsonResponse<{ ok: boolean; email: string }>(response);
}

// ── /admin/groups ──

export type GroupItem = {
  id: string;
  name: string;
  description: string;
  createdAt: string;
  createdBy: string;
  memberCount: number;
};

export async function listGroups(): Promise<GroupItem[]> {
  const response = await apiFetch(apiPath("/admin/groups"));
  const payload = await parseJsonResponse<{ groups: GroupItem[] }>(response);
  return payload.groups ?? [];
}

export async function addGroup(name: string, description?: string): Promise<GroupItem> {
  const response = await apiFetch(apiPath("/admin/groups"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(description ? { name, description } : { name }),
  });
  return parseJsonResponse<GroupItem>(response);
}

export async function deleteGroup(groupId: string): Promise<void> {
  const response = await apiFetch(apiPath(`/admin/groups/${encodeURIComponent(groupId)}`), {
    method: "DELETE",
  });
  await parseJsonResponse<{ ok: boolean; id: string }>(response);
}

export type GroupSourceItem = {
  id: string;
  name: string;
  kind?: string;
  status?: string;
  error?: string | null;
  url?: string | null;
};

/** Drive folder links expand into several records on the backend. */
export type FolderSourceResult = { folder: true; count: number; records: GroupSourceItem[] };

export async function listGroupSources(groupId: string): Promise<GroupSourceItem[]> {
  const response = await apiFetch(
    apiPath(`/admin/groups/${encodeURIComponent(groupId)}/sources`),
  );
  const payload = await parseJsonResponse<{ sources: GroupSourceItem[] }>(response);
  return payload.sources ?? [];
}

export async function addGroupTextSource(
  groupId: string,
  name: string,
  text: string,
): Promise<GroupSourceItem> {
  const response = await apiFetch(
    apiPath(`/admin/groups/${encodeURIComponent(groupId)}/sources/text`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, text }),
    },
  );
  return parseJsonResponse<GroupSourceItem>(response);
}

export async function addGroupUrlSource(
  groupId: string,
  url: string,
): Promise<GroupSourceItem | FolderSourceResult> {
  const response = await apiFetch(
    apiPath(`/admin/groups/${encodeURIComponent(groupId)}/sources/url`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    },
  );
  return parseJsonResponse<GroupSourceItem | FolderSourceResult>(response);
}

/** Multipart upload of a group source with progress reporting. */
export async function uploadGroupSourceFile(
  groupId: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<GroupSourceItem> {
  const form = new FormData();
  form.append("file", file);
  return (await xhrUpload(
    "POST",
    apiPath(`/admin/groups/${encodeURIComponent(groupId)}/sources/upload`),
    form,
    await authHeaders(),
    onProgress,
  )) as GroupSourceItem;
}

export async function deleteGroupSource(groupId: string, sourceId: string): Promise<void> {
  const response = await apiFetch(
    apiPath(
      `/admin/groups/${encodeURIComponent(groupId)}/sources/${encodeURIComponent(sourceId)}`,
    ),
    { method: "DELETE" },
  );
  await parseJsonResponse<{ ok: boolean; sourceId: string }>(response);
}

// ── /admin/agents (agent profiles) ──

export type AgentProfileItem = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  /** template/soul/style/agents/goal texts; empty = inherit global persona. */
  persona: Record<string, string>;
  model: string;
  temperature: number | null;
  skills: string[];
  customSkillIds: string[];
  useSources: boolean;
  escalationAgentId: string;
  confidenceThreshold: number;
  createdAt: string;
  createdBy: string;
  updatedAt: string;
};

export type AgentProfilePatch = Partial<
  Pick<
    AgentProfileItem,
    | "name"
    | "description"
    | "enabled"
    | "persona"
    | "model"
    | "temperature"
    | "skills"
    | "customSkillIds"
    | "useSources"
    | "escalationAgentId"
    | "confidenceThreshold"
  >
>;

export type AgentProfileOptions = {
  models: string[];
  sdkSkills: string[];
  customSkills: string[];
  escalationTargets: { id: string; name: string }[];
  defaults: { confidenceThreshold: number };
};

export async function listAgents(): Promise<AgentProfileItem[]> {
  const response = await apiFetch(apiPath("/admin/agents"));
  const payload = await parseJsonResponse<{ agents: AgentProfileItem[] }>(response);
  return payload.agents ?? [];
}

export async function getAgentOptions(): Promise<AgentProfileOptions> {
  const response = await apiFetch(apiPath("/admin/agents/options"));
  return parseJsonResponse<AgentProfileOptions>(response);
}

export async function addAgent(name: string, description: string): Promise<AgentProfileItem> {
  const response = await apiFetch(apiPath("/admin/agents"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
  return parseJsonResponse<AgentProfileItem>(response);
}

export async function updateAgent(
  agentId: string,
  patch: AgentProfilePatch,
): Promise<AgentProfileItem> {
  const response = await apiFetch(apiPath(`/admin/agents/${encodeURIComponent(agentId)}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJsonResponse<AgentProfileItem>(response);
}

export async function deleteAgent(agentId: string): Promise<void> {
  const response = await apiFetch(apiPath(`/admin/agents/${encodeURIComponent(agentId)}`), {
    method: "DELETE",
  });
  await parseJsonResponse<{ ok: boolean; id: string }>(response);
}

export async function listAgentSources(agentId: string): Promise<GroupSourceItem[]> {
  const response = await apiFetch(
    apiPath(`/admin/agents/${encodeURIComponent(agentId)}/sources`),
  );
  const payload = await parseJsonResponse<{ sources: GroupSourceItem[] }>(response);
  return payload.sources ?? [];
}

export async function addAgentTextSource(
  agentId: string,
  name: string,
  text: string,
): Promise<GroupSourceItem> {
  const response = await apiFetch(
    apiPath(`/admin/agents/${encodeURIComponent(agentId)}/sources/text`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, text }),
    },
  );
  return parseJsonResponse<GroupSourceItem>(response);
}

export async function addAgentUrlSource(
  agentId: string,
  url: string,
): Promise<GroupSourceItem | FolderSourceResult> {
  const response = await apiFetch(
    apiPath(`/admin/agents/${encodeURIComponent(agentId)}/sources/url`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    },
  );
  return parseJsonResponse<GroupSourceItem | FolderSourceResult>(response);
}

/** Multipart upload of an agent source with progress reporting. */
export async function uploadAgentSourceFile(
  agentId: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<GroupSourceItem> {
  const form = new FormData();
  form.append("file", file);
  return (await xhrUpload(
    "POST",
    apiPath(`/admin/agents/${encodeURIComponent(agentId)}/sources/upload`),
    form,
    await authHeaders(),
    onProgress,
  )) as GroupSourceItem;
}

export async function deleteAgentSource(agentId: string, sourceId: string): Promise<void> {
  const response = await apiFetch(
    apiPath(
      `/admin/agents/${encodeURIComponent(agentId)}/sources/${encodeURIComponent(sourceId)}`,
    ),
    { method: "DELETE" },
  );
  await parseJsonResponse<{ ok: boolean; sourceId: string }>(response);
}

// ── /admin/capabilities ──

export type CapabilityDefinition = {
  id: string;
  kind: "route" | "global";
  label: string;
  description: string;
  default: boolean;
};

export type CapabilitiesState = {
  definitions: CapabilityDefinition[];
  roles: { user: Record<string, boolean> };
  /** Sparse per-group overrides; null in a PUT removes an override. */
  groups?: Record<string, Record<string, boolean>>;
  global: Record<string, boolean>;
};

export async function getCapabilities(): Promise<CapabilitiesState> {
  const response = await apiFetch(apiPath("/admin/capabilities"));
  return parseJsonResponse<CapabilitiesState>(response);
}

/** Partial update; the backend returns the full resolved state. */
export async function putCapabilities(patch: {
  roles?: { user: Record<string, boolean> };
  groups?: Record<string, Record<string, boolean | null>>;
  global?: Record<string, boolean>;
}): Promise<CapabilitiesState> {
  const response = await apiFetch(apiPath("/admin/capabilities"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJsonResponse<CapabilitiesState>(response);
}

// ── /admin/runtime-settings ──

export type RuntimeSettingsState = {
  values: Record<string, string>;
  options: Record<string, string[]>;
};

export async function getRuntimeSettings(): Promise<RuntimeSettingsState> {
  const response = await apiFetch(apiPath("/admin/runtime-settings"));
  return parseJsonResponse<RuntimeSettingsState>(response);
}

/** Partial update; the backend returns the full resolved state. */
export async function putRuntimeSettings(
  patch: Record<string, string>,
): Promise<RuntimeSettingsState> {
  const response = await apiFetch(apiPath("/admin/runtime-settings"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJsonResponse<RuntimeSettingsState>(response);
}

// ── /account/usage + /admin/usage ──

export type UsageSummary = {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  costUsd: number;
  calls: number;
};

export type QuotaStatus = {
  limit: number;
  used: number;
  warning: boolean;
  percent: number;
};

export type UsageRow = {
  ts: string;
  sessionId: string;
  model: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  costUsd: number;
};

export type AccountUsage = UsageSummary & {
  month: string;
  quota: QuotaStatus;
  recent: UsageRow[];
};

export async function getAccountUsage(): Promise<AccountUsage> {
  const response = await apiFetch(apiPath("/account/usage"));
  return parseJsonResponse<AccountUsage>(response);
}

export type AdminUsage = {
  month: string;
  totals: UsageSummary;
  users: (UsageSummary & { owner: string; quota: QuotaStatus })[];
};

export async function getAdminUsage(month?: string): Promise<AdminUsage> {
  const suffix = month ? `?month=${encodeURIComponent(month)}` : "";
  const response = await apiFetch(apiPath(`/admin/usage${suffix}`));
  return parseJsonResponse<AdminUsage>(response);
}

// ── /admin/pricing + /admin/quotas ──

export type PricingState = {
  models: Record<string, { input_per_1m: number; output_per_1m: number }>;
};

export async function getPricing(): Promise<PricingState> {
  const response = await apiFetch(apiPath("/admin/pricing"));
  return parseJsonResponse<PricingState>(response);
}

export async function putPricing(patch: PricingState): Promise<PricingState> {
  const response = await apiFetch(apiPath("/admin/pricing"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJsonResponse<PricingState>(response);
}

export type QuotasState = {
  defaultMonthlyTokens: number;
  overrides: Record<string, number>;
};

export async function getQuotas(): Promise<QuotasState> {
  const response = await apiFetch(apiPath("/admin/quotas"));
  return parseJsonResponse<QuotasState>(response);
}

export async function putQuotas(patch: Partial<QuotasState>): Promise<QuotasState> {
  const response = await apiFetch(apiPath("/admin/quotas"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJsonResponse<QuotasState>(response);
}

// ── /admin/audit ──

export type AuditEntry = {
  ts: string;
  actor: string;
  role: string;
  action: string;
  target: string;
  detail: Record<string, unknown>;
  status: string;
};

export type AuditPageResult = {
  items: AuditEntry[];
  total: number;
};

export type AuditFilters = {
  actor?: string;
  action?: string;
  since?: string;
  until?: string;
};

function auditQuery(filters: AuditFilters, limit?: number, offset?: number): string {
  const params = new URLSearchParams();
  if (filters.actor) params.set("actor", filters.actor);
  if (filters.action) params.set("action", filters.action);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function getAuditEntries(
  filters: AuditFilters,
  limit: number,
  offset: number,
): Promise<AuditPageResult> {
  const response = await apiFetch(apiPath(`/admin/audit${auditQuery(filters, limit, offset)}`));
  return parseJsonResponse<AuditPageResult>(response);
}

export async function exportAuditCsv(filters: AuditFilters): Promise<Blob> {
  const response = await apiFetch(apiPath(`/admin/audit/export${auditQuery(filters)}`));
  if (!response.ok) {
    throw new Error(`Ekspor audit gagal (${response.status})`);
  }
  return response.blob();
}

// ── /admin/privacy ──

export type PrivacySettings = {
  retentionDays: number;
  piiRedaction: boolean;
};

export async function getPrivacySettings(): Promise<PrivacySettings> {
  const response = await apiFetch(apiPath("/admin/privacy"));
  return parseJsonResponse<PrivacySettings>(response);
}

/** Partial update; the backend returns the full resolved state. */
export async function putPrivacySettings(
  patch: Partial<PrivacySettings>,
): Promise<PrivacySettings> {
  const response = await apiFetch(apiPath("/admin/privacy"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJsonResponse<PrivacySettings>(response);
}

export type PrivacySweepResult = {
  deletedSessions: number;
  ownersScanned: number;
};

export async function runPrivacySweep(): Promise<PrivacySweepResult> {
  const response = await apiFetch(apiPath("/admin/privacy/sweep"), { method: "POST" });
  return parseJsonResponse<PrivacySweepResult>(response);
}

// ── /admin/persona ──

export type PersonaSettings = {
  template: string | null;
  soul: string;
  style: string;
  agents: string;
  goal: string;
  source_context_label: string;
};

export type PersonaActive = {
  source?: string;
  soul_chars?: number;
  style_chars?: number;
  agents_chars?: number;
  total_chars?: number;
};

export type PersonaState = {
  settings: PersonaSettings | null;
  source: "db" | "env" | "files";
  active: PersonaActive;
};

export type PersonaTemplate = {
  id: string;
  name: string;
  description: string;
  soul: string;
  style: string;
  agents: string;
  goal: string;
  sourceContextLabel: string;
};

export async function getPersona(): Promise<PersonaState> {
  const response = await apiFetch(apiPath("/admin/persona"));
  return parseJsonResponse<PersonaState>(response);
}

export async function listPersonaTemplates(): Promise<PersonaTemplate[]> {
  const response = await apiFetch(apiPath("/admin/persona/templates"));
  const payload = await parseJsonResponse<{ templates: PersonaTemplate[] }>(response);
  return payload.templates ?? [];
}

export type PersonaPutResult = {
  ok: boolean;
  settings: PersonaSettings;
  source: PersonaState["source"];
  active: PersonaActive;
};

export async function applyPersonaTemplate(templateId: string): Promise<PersonaPutResult> {
  const response = await apiFetch(apiPath("/admin/persona"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template: templateId }),
  });
  return parseJsonResponse<PersonaPutResult>(response);
}

export async function savePersona(settings: {
  soul: string;
  style: string;
  agents: string;
  goal: string;
  source_context_label?: string;
}): Promise<PersonaPutResult> {
  const response = await apiFetch(apiPath("/admin/persona"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  return parseJsonResponse<PersonaPutResult>(response);
}

// ── /admin/shared-sources ──

export async function listSharedSources(): Promise<SharedSource[]> {
  const response = await apiFetch(apiPath("/admin/shared-sources"));
  const payload = await parseJsonResponse<{ sources: SharedSource[] }>(response);
  return payload.sources ?? [];
}

export async function addSharedTextSource(name: string, text: string): Promise<SharedSource> {
  const response = await apiFetch(apiPath("/admin/shared-sources/text"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, text }),
  });
  return parseJsonResponse<SharedSource>(response);
}

export async function addSharedUrlSource(url: string): Promise<SharedSource> {
  const response = await apiFetch(apiPath("/admin/shared-sources/url"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  return parseJsonResponse<SharedSource>(response);
}

export async function deleteSharedSource(sourceId: string): Promise<void> {
  const response = await apiFetch(
    apiPath(`/admin/shared-sources/${encodeURIComponent(sourceId)}`),
    { method: "DELETE" },
  );
  await parseJsonResponse<{ ok: boolean; sourceId: string }>(response);
}

/** Multipart upload of a global shared source. Plain fetch (no progress
 * callback) is enough for admin uploads. */
export async function uploadSharedSourceFile(file: File): Promise<SharedSource> {
  const form = new FormData();
  form.append("file", file);
  const response = await apiFetch(apiPath("/admin/shared-sources/upload"), {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  return parseJsonResponse<SharedSource>(response);
}
