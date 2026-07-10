import { ChatPanel, ChatProvider } from "@openbench/chat-ui";
import { useMemo } from "react";
import { transcribeAudio } from "../api";
import { buildChatConfig } from "../chat/config";
import { ErrorBoundary } from "../ErrorBoundary";

const TEST_SUGGESTIONS = [
  "Summarize what the sources cover",
  "Ask something only a source can answer",
  "Ask something off-source to verify the refusal",
];

/** Right-side drawer where the admin talks to the exact chat guests get:
 * same curated grounding, same disabled composer attachments. */
export function TestChatDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const chatConfig = useMemo(buildChatConfig, []);

  if (!open) return null;

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-label="Test chat">
        <div className="drawer__header">
          <div className="drawer__title">Test chat</div>
          <button type="button" className="drawer__close" onClick={onClose} aria-label="Close">
            <svg
              aria-hidden="true"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="drawer__body drawer__body--chat">
          <ErrorBoundary region="the test chat">
            <ChatProvider config={chatConfig}>
              <ChatPanel
                title="Test chat"
                greeting="Test the curated knowledge base"
                suggestions={TEST_SUGGESTIONS}
                placeholder="Ask exactly what a user would ask..."
                allowAttachments={false}
                onTranscribe={transcribeAudio}
              />
            </ChatProvider>
          </ErrorBoundary>
        </div>
      </aside>
    </>
  );
}
