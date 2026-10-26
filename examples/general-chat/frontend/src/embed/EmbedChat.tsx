/** Standalone single-agent chat for iframe embeds (`/embed/<agentId>?key=`).
 *
 * No Firebase, no sidebar, no uploads: the embed key is the only
 * credential and it is scoped by the backend to `/agents/<id>/...`. The
 * SDK sends it as the Bearer token on every stream/action request. */
import { ChatPanel, ChatProvider, type ChatConfig } from "@openbench/chat-ui";
import { useEffect, useMemo, useState } from "react";
import type { PublicAgentInfo } from "../account/api";
import { apiPath } from "../api";
import { ErrorBoundary } from "../ErrorBoundary";

const MSG_INVALID_KEY = "Kunci embed tidak valid.";
const MSG_UNAVAILABLE = "Kunci embed tidak valid atau agen tidak tersedia.";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; agent: PublicAgentInfo }
  | { status: "error"; message: string };

export function EmbedChat({
  agentId,
  embedKey,
  theme,
}: {
  agentId: string;
  embedKey: string;
  theme: "light" | "dark" | null;
}) {
  const [state, setState] = useState<LoadState>(() =>
    embedKey ? { status: "loading" } : { status: "error", message: MSG_INVALID_KEY },
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme ?? "light");
    document.body.classList.add("embed-root");
    return () => document.body.classList.remove("embed-root");
  }, [theme]);

  useEffect(() => {
    if (!embedKey) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(apiPath(`/agents/${encodeURIComponent(agentId)}`), {
          headers: { Authorization: `Bearer ${embedKey}` },
        });
        if (!response.ok) throw new Error(String(response.status));
        const agent = (await response.json()) as PublicAgentInfo;
        if (!cancelled) setState({ status: "ready", agent });
      } catch {
        if (!cancelled) setState({ status: "error", message: MSG_UNAVAILABLE });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [agentId, embedKey]);

  const chatConfig = useMemo<ChatConfig>(() => {
    const base = `/agents/${encodeURIComponent(agentId)}`;
    return {
      streamUrl: apiPath(`${base}/awp`),
      actionUrl: apiPath(`${base}/chat/action`),
      // The backend answers 501 so the SDK skips session history cleanly.
      sessionsUrl: apiPath(`${base}/sessions`),
      getAuthToken: async () => embedKey,
      tableExport: { enabled: false },
    };
  }, [agentId, embedKey]);

  if (state.status === "error") {
    return (
      <div className="embed-error" role="alert">
        {state.message}
      </div>
    );
  }
  if (state.status === "loading") {
    return <div className="embed-error">Memuat agen…</div>;
  }

  return (
    <ChatProvider config={chatConfig}>
      <ErrorBoundary region="embed">
        <div className="embed-chat">
          <ChatPanel
            title={state.agent.name}
            greeting={state.agent.description || state.agent.name}
            placeholder="Tulis pesan…"
            allowAttachments={false}
          />
        </div>
      </ErrorBoundary>
    </ChatProvider>
  );
}
