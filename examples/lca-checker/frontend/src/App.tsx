/**
 * LCA Compliance Checker
 *
 * Fullscreen chat interface for ISO 14040/14044 LCA compliance checking.
 * Uses ChatProvider + ChatPanel from @openbench/chat-ui.
 */

import {
  ChatPanel,
  ChatProvider,
  SessionSidebar,
  useChatContext,
} from "@openbench/chat-ui";
import { useEffect, useState } from "react";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import "./global.css";

const STREAM_URL = "/awp";

const SUGGESTIONS = [
  "Check ISO 14044 compliance for LCA-2024-001",
  "Compare impact results with packaging benchmarks",
  "What does ISO say about allocation procedures for co-products?",
  "How does Japfa implement LCA for aquaculture operations?",
  "What is Japfa's Sustainability-Linked Bond (SLB) commitment?",
  "Search Japfa report for greenhouse gas emission reduction targets",
  "What are Japfa's water recycling and conservation initiatives?",
  "How does Japfa address animal welfare in their sustainability report?",
];

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

// ── Sun/Moon icon ──

function ThemeIcon({ dark }: { dark: boolean }) {
  if (dark) {
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
        title="LCA Compliance Checker"
        suggestions={SUGGESTIONS}
        placeholder="Ask about ISO 14044, Japfa sustainability report, or Pedoman KLH..."
        greeting="Welcome to LCA Compliance Checker"
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
