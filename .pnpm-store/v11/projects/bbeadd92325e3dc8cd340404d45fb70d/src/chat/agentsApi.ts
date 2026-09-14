/** User-facing agent picker API (/chat/agents, /chat/agent-selection). */

import { parseJsonResponse } from "../account/api";
import { apiFetch, apiPath } from "../api";

export type ChatAgentItem = {
  id: string;
  name: string;
  description: string;
};

export type ChatAgentList = {
  agents: ChatAgentItem[];
  defaultMode: "auto" | "default";
};

export async function listChatAgents(): Promise<ChatAgentList> {
  const response = await apiFetch(apiPath("/chat/agents"));
  return parseJsonResponse<ChatAgentList>(response);
}

/** "" = default assistant, "auto" = router picks, otherwise an agent id. */
export async function getAgentSelection(threadId: string): Promise<string> {
  const response = await apiFetch(
    apiPath(`/chat/agent-selection?threadId=${encodeURIComponent(threadId)}`),
  );
  const payload = await parseJsonResponse<{ agentId: string }>(response);
  return payload.agentId ?? "";
}

export async function putAgentSelection(threadId: string, agentId: string): Promise<void> {
  const response = await apiFetch(apiPath("/chat/agent-selection"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ threadId, agentId }),
  });
  await parseJsonResponse<{ ok: boolean; agentId: string }>(response);
}
