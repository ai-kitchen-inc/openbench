import { ChatPanel, ChatProvider, SessionSidebar, useChatContext } from "@openbench/chat-ui";
import { useMemo, useState } from "react";
import { transcribeAudio, type AuthUser } from "../api";
import { BookIcon } from "../brand/icons";
import { buildChatConfig } from "../chat/config";
import { ErrorBoundary } from "../ErrorBoundary";
import { APP_NAME, COMMON } from "../i18n/id";
import { useDarkMode, ThemeIcon } from "../theme";
import { SourcesDrawer } from "./SourcesDrawer";

const GUEST_SUGGESTIONS = [
  "Apa saja yang dicakup oleh sumber?",
  "Ringkas isi basis pengetahuan",
  "Dari mana jawaban itu berasal?",
];

/** Chat-only surface for guests: curated grounding, cited answers, no
 * source management and no composer attachments. */
export function GuestChat({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  const chatConfig = useMemo(buildChatConfig, []);

  return (
    <ChatProvider config={chatConfig}>
      <ErrorBoundary region="percakapan">
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
          title={APP_NAME}
          greeting="Tanyakan apa saja seputar basis pengetahuan resmi"
          suggestions={GUEST_SUGGESTIONS}
          placeholder="Ketik pertanyaan — jawaban akan mengutip sumber resmi..."
          allowAttachments={false}
          onTranscribe={transcribeAudio}
          headerRight={
            <div className="chat-header-actions">
              <button
                type="button"
                className="panel-button"
                onClick={() => setSourcesOpen(true)}
              >
                <BookIcon size={14} />
                Sumber
              </button>
              <span className="auth-user" title={user.username}>
                {user.username}
              </span>
              <button
                type="button"
                className="theme-toggle"
                onClick={toggleDark}
                title={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
                aria-label={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
              >
                <ThemeIcon dark={dark} />
              </button>
              <button type="button" className="auth-signout" onClick={onSignOut}>
                {COMMON.signOut}
              </button>
            </div>
          }
        />
      </div>
      <SourcesDrawer open={sourcesOpen} onClose={() => setSourcesOpen(false)} />
    </div>
  );
}
