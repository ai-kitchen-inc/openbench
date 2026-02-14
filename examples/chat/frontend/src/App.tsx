/**
 * Fullscreen chat demo using ChatProvider + ChatPanel hooks.
 *
 * Uses the proper hook chain: ChatProvider → useChat → useChatTransport + useA2UIProcessor.
 * No bypassing — this exercises the full SDK as intended.
 */

import { ChatPanel, ChatProvider, SessionSidebar, useChatContext } from "@openbench/chat-ui";
import "@openbench/chat-ui/styles/chat-ui.css";
import "./global.css";

const WS_URL = `ws://${window.location.host}/chat/ws`;
const STREAM_URL = "/chat/stream";

const SUGGESTIONS = [
  "Show me a sales chart",
  "What are the latest AI trends?",
  "Open registration form",
  "Compare solar and wind energy",
];

function ChatLayout() {
  const { sidebarOpen } = useChatContext();

  return (
    <div className="chat-layout">
      {sidebarOpen && <SessionSidebar />}
      <ChatPanel
        suggestions={SUGGESTIONS}
        placeholder="Try: chart, pie, form, file..."
        greeting="Welcome to OpenBench Chat"
      />
    </div>
  );
}

export default function App() {
  return (
    <ChatProvider config={{ wsUrl: WS_URL, streamUrl: STREAM_URL }}>
      <ChatLayout />
    </ChatProvider>
  );
}
