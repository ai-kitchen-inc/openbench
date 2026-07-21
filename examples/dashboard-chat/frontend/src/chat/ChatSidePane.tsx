import { ChatPanel, ChatProvider, useChatContext } from "@openbench/chat-ui";
import { useEffect, useMemo, useRef } from "react";
import { getDashboard, type AuthUser } from "../api";
import { buildChatConfig } from "./config";

const SUGGESTIONS = [
  "Add a panel for revenue by store",
  "Turn the trend chart into a bar chart",
  "Which panels would you add for this schema?",
];

const INITIAL_PROMPT =
  "Look at my database schema and generate an initial dashboard with the most useful KPIs and charts.";

export function ChatSidePane({
  user,
  onTurnComplete,
}: {
  user: AuthUser;
  onTurnComplete: () => void;
}) {
  const chatConfig = useMemo(buildChatConfig, []);

  return (
    <ChatProvider config={chatConfig}>
      <PaneInner user={user} onTurnComplete={onTurnComplete} />
    </ChatProvider>
  );
}

function PaneInner({ user, onTurnComplete }: { user: AuthUser; onTurnComplete: () => void }) {
  const { sessions, activeSessionId, switchSession, isStreaming, sendMessage } = useChatContext();

  // The backend pins every stream to this id regardless of what the
  // client sends; switching to it makes history hydrate after reloads.
  const serverSessionId = `user-${user.username}`;
  const switchedRef = useRef(false);
  useEffect(() => {
    if (switchedRef.current) return;
    if (sessions.some((session) => session.id === serverSessionId)) {
      switchedRef.current = true;
      if (activeSessionId !== serverSessionId) {
        switchSession(serverSessionId);
      }
    }
  }, [sessions, activeSessionId, serverSessionId, switchSession]);

  // First-run kickoff: no dashboard yet -> ask the agent to build one.
  // Waits for an active session — sendMessage is a no-op without one.
  const kickoffRef = useRef(false);
  useEffect(() => {
    if (kickoffRef.current || activeSessionId === null) return;
    kickoffRef.current = true;
    void getDashboard().then((spec) => {
      if (spec === null) {
        sendMessage(INITIAL_PROMPT);
      }
    });
    // sendMessage identity is stable enough for a run-once effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId]);

  // Fire onTurnComplete on every streaming true -> false edge so the
  // canvas refetches the (possibly updated) dashboard spec.
  const wasStreamingRef = useRef(false);
  useEffect(() => {
    if (wasStreamingRef.current && !isStreaming) {
      onTurnComplete();
    }
    wasStreamingRef.current = isStreaming;
  }, [isStreaming, onTurnComplete]);

  return (
    <div className="chat-pane">
      <ChatPanel
        title="Assistant"
        greeting="Ask me to change the dashboard — add panels, switch chart types, refine queries."
        suggestions={SUGGESTIONS}
        placeholder="Describe a dashboard change…"
        allowAttachments={false}
      />
    </div>
  );
}
