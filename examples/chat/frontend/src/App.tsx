/**
 * Fullscreen chat demo using ChatProvider + ChatPanel hooks.
 *
 * Uses the proper hook chain: ChatProvider → useChat → useA2UIProcessor.
 * No bypassing — this exercises the full SDK as intended.
 */

import { ChatPanel, ChatProvider, SessionSidebar, useChatContext } from "@openbench/chat-ui";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import "./global.css";

const STREAM_URL = "/chat/stream";

const SUGGESTIONS = [
  "Search the web for latest AI agent trends",
  "Upload a PDF and summarize it",
  "Calculate the ROI: 150000 / 42000 * 100",
  "Compare solar vs wind energy costs",
];

function ChatLayout() {
  const { sidebarOpen } = useChatContext();

  return (
    <div className="chat-layout">
      {sidebarOpen && <SessionSidebar />}
      <ChatPanel
        title="OpenBench"
        suggestions={SUGGESTIONS}
        placeholder="Ask anything, search the web, or upload a file..."
        greeting="Welcome to OpenBench Chat"
      />
    </div>
  );
}

export default function App() {
  return (
    <ChatProvider config={{ streamUrl: STREAM_URL }}>
      <ChatLayout />
    </ChatProvider>
  );
}
