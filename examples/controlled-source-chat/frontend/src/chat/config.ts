import type { ChatConfig } from "@openbench/chat-ui";
import { apiPath, getStoredToken } from "../api";

/** ChatConfig shared by the admin test chat and the guest chat.
 * No uploadFile: composer attachments are disabled everywhere —
 * grounding comes exclusively from the admin-curated sources. */
export function buildChatConfig(): ChatConfig {
  return {
    streamUrl: apiPath("/awp"),
    actionUrl: apiPath("/chat/action"),
    sessionsUrl: apiPath("/sessions"),
    getAuthToken: async () => getStoredToken(),
  };
}
