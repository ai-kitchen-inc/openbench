import type { ChatConfig } from "@openbench/chat-ui";
import { apiPath, getStoredToken } from "../api";

/** Transport config for the dashboard copilot side pane.
 * No uploadFile: attachments are disabled — the assistant works from the
 * database schema, not from user files. */
export function buildChatConfig(): ChatConfig {
  return {
    streamUrl: apiPath("/awp"),
    sessionsUrl: apiPath("/sessions"),
    getAuthToken: async () => getStoredToken(),
  };
}
