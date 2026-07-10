import { ChatPanel, ChatProvider, SessionSidebar, useChatContext } from "@openbench/chat-ui";
import { useMemo, useState } from "react";
import { transcribeAudio, type AuthUser } from "../api";
import { buildChatConfig } from "../chat/config";
import { ErrorBoundary } from "../ErrorBoundary";
import { useDarkMode, ThemeIcon } from "../theme";
import { SourcesDrawer } from "./SourcesDrawer";

const GUEST_SUGGESTIONS = [
  "What do the sources cover?",
  "Summarize the knowledge base",
  "Where does that answer come from?",
];

/** Chat-only surface for guests: curated grounding, cited answers, no
 * source management and no composer attachments. */
export function GuestChat({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  const chatConfig = useMemo(buildChatConfig, []);

  return (
    <ChatProvider config={chatConfig}>
      <ErrorBoundary region="chat">
        <GuestLayout user={user} onSignOut={onSignOut} />
      </ErrorBoundary>
    </ChatProvider>
  );
}

function GuestLayout({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  const { sidebarOpen } = useChatContext();
  const [dark, toggleDark] = useDarkMode();
  const [sourcesOpen, setSourcesOpen] = useState(false);

  return (
    <div className="guest-layout">
      {sidebarOpen && (
        <div className="guest-layout__sidebar">
          <SessionSidebar />
        </div>
      )}
      <div className="guest-layout__main">
        <ChatPanel
          title="Controlled Source Chat"
          greeting="Ask about the curated knowledge base"
          suggestions={GUEST_SUGGESTIONS}
          placeholder="Ask a question — answers cite the curated sources..."
          allowAttachments={false}
          onTranscribe={transcribeAudio}
          headerRight={
            <div className="chat-header-actions">
              <button
                type="button"
                className="panel-button"
                onClick={() => setSourcesOpen(true)}
              >
                Sources
              </button>
              <span className="auth-user" title={user.username}>
                {user.username}
              </span>
              <button
                type="button"
                className="theme-toggle"
                onClick={toggleDark}
                title={dark ? "Switch to light mode" : "Switch to dark mode"}
                aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
              >
                <ThemeIcon dark={dark} />
              </button>
              <button type="button" className="auth-signout" onClick={onSignOut}>
                Sign out
              </button>
            </div>
          }
        />
      </div>
      <SourcesDrawer open={sourcesOpen} onClose={() => setSourcesOpen(false)} />
    </div>
  );
}
