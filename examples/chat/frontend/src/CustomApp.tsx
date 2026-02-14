/**
 * Hook-based custom UI example using useChat() + SurfaceRenderer.
 *
 * Demonstrates how to build a completely custom chat interface
 * while still using the OpenBench transport and A2UI rendering.
 *
 * To use this instead of App.tsx, change the import in main.tsx:
 *   import App from './CustomApp';
 */

import { ChatProvider, SurfaceRenderer, useChatContext } from "@openbench/chat-ui";
import { useState } from "react";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";

const STREAM_URL = "/chat/stream";

function CustomChat() {
  const { messages, sendMessage, isStreaming, connectionStatus, sendAction } = useChatContext();

  const [input, setInput] = useState("");

  const handleSend = () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    sendMessage(text);
    setInput("");
  };

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: 24, fontFamily: "system-ui" }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>Custom Chat UI</h1>
      <p style={{ fontSize: 13, color: "#666", marginBottom: 24 }}>
        Built with <code>useChat()</code> hook &mdash; status: {connectionStatus}
      </p>

      {/* Message list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 24 }}>
        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              padding: 12,
              borderRadius: 8,
              background: msg.role === "user" ? "#f0f0f0" : "#fafafa",
              border: "1px solid rgba(0,0,0,0.08)",
            }}
          >
            <div style={{ fontSize: 11, color: "#999", marginBottom: 4 }}>
              {msg.role === "user" ? "You" : "Assistant"}
              {msg.status === "streaming" && " (streaming...)"}
            </div>

            {/* Text content */}
            {msg.content && (
              <div style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>{msg.content}</div>
            )}

            {/* A2UI surfaces */}
            {msg.surfaces?.map((surface) => (
              <SurfaceRenderer key={surface.surfaceId} surface={surface} onAction={sendAction} />
            ))}
          </div>
        ))}
      </div>

      {/* Input */}
      <div style={{ display: "flex", gap: 8 }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Try: chart, pie, form, file..."
          disabled={isStreaming}
          style={{
            flex: 1,
            padding: "10px 14px",
            fontSize: 14,
            border: "1px solid #ddd",
            borderRadius: 8,
            outline: "none",
          }}
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={isStreaming || !input.trim()}
          style={{
            padding: "10px 20px",
            fontSize: 14,
            background: "#1a1a1a",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            cursor: "pointer",
            opacity: isStreaming || !input.trim() ? 0.5 : 1,
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}

export default function CustomApp() {
  return (
    <ChatProvider config={{ streamUrl: STREAM_URL }}>
      <CustomChat />
    </ChatProvider>
  );
}
