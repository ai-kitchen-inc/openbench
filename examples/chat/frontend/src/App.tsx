/**
 * Fullscreen chat demo using ChatProvider + ChatPanel hooks.
 *
 * Showcases SDK features:
 *   - ChatProvider + ChatPanel hook chain
 *   - Session sidebar with multi-session support
 *   - Dark mode via CSS custom properties (--ob-* overrides)
 *   - Custom component registration (registerCustomComponent)
 *   - All standard + custom A2UI components
 */

import {
  ChatPanel,
  ChatProvider,
  registerCustomComponent,
  SessionSidebar,
  useChatContext,
} from "@openbench/chat-ui";
import { useEffect, useState } from "react";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import "./global.css";

const STREAM_URL = "/awp";

const SUGGESTIONS = [
  "Search the web for latest AI agent trends",
  "Compare solar vs wind energy costs with a chart",
  "Write a Python quicksort implementation",
  "Compare solar, wind, and storage in tabs",
  "List the top 5 renewable energy sources",
  "What did we discuss earlier?",
];

// ── Custom component demo ──
// Demonstrates registerCustomComponent() extensibility API.
// This registers an "ObStatusBadge" renderer that the backend could emit.

registerCustomComponent("ObStatusBadge", ({ properties }) => {
  const { label = "Status", variant = "default" } = properties as {
    label?: string;
    variant?: "success" | "warning" | "error" | "default";
  };
  const colors: Record<string, string> = {
    success: "#37b24d",
    warning: "#f59f00",
    error: "#eb5757",
    default: "#787774",
  };
  const color = colors[variant] ?? colors.default;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 10px",
        borderRadius: 12,
        fontSize: "0.75rem",
        fontWeight: 600,
        background: `${color}14`,
        color,
        border: `1px solid ${color}33`,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: color }} />
      {label}
    </span>
  );
});

// ── Dark mode hook ──

function useDarkMode() {
  const [dark, setDark] = useState(() => {
    if (typeof window !== "undefined") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    return false;
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }, [dark]);

  return [dark, () => setDark((d) => !d)] as const;
}

// ── Sun/Moon icon (inline SVG, no extra dep) ──

function ThemeIcon({ dark }: { dark: boolean }) {
  if (dark) {
    // Sun icon (Lucide)
    return (
      <svg
        aria-hidden="true"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
      </svg>
    );
  }
  // Moon icon (Lucide)
  return (
    <svg
      aria-hidden="true"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </svg>
  );
}

function ChatLayout() {
  const { sidebarOpen } = useChatContext();
  const [dark, toggleDark] = useDarkMode();

  return (
    <div className="chat-layout">
      {sidebarOpen && <SessionSidebar />}
      <ChatPanel
        title="OpenBench"
        suggestions={SUGGESTIONS}
        placeholder="Ask anything, search the web, or upload a file..."
        greeting="Welcome to OpenBench Chat"
        headerRight={
          <button
            type="button"
            className="theme-toggle"
            onClick={toggleDark}
            title={dark ? "Switch to light mode" : "Switch to dark mode"}
            aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
          >
            <ThemeIcon dark={dark} />
          </button>
        }
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
