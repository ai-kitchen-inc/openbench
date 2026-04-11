/**
 * LCI Mini — Persona Layer demo frontend.
 *
 * Minimal chat UI for Lici, an LCI/LCA consultant assistant whose identity
 * is loaded from soul/SOUL.md + soul/STYLE.md + soul/AGENTS.md at the
 * server. The sidebar panel below the session list shows what was loaded.
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
  "Jelaskan perbedaan cradle-to-gate dan cradle-to-grave",
  "Bagaimana memilih functional unit untuk pabrik semen?",
  "Apa saja kriteria PROPER Emas untuk LCA?",
  "Kenapa CO2 biasanya jadi hotspot utama di kilang minyak?",
  "Bedanya mass allocation vs economic allocation?",
];

// ── Persona summary (fetched from /persona) ──

type PersonaSummary = {
  loaded: boolean;
  source?: string;
  soul_chars?: number;
  style_chars?: number;
  agents_chars?: number;
  total_chars?: number;
};

function PersonaBadge() {
  const [persona, setPersona] = useState<PersonaSummary | null>(null);

  useEffect(() => {
    fetch("/persona")
      .then((r) => r.json())
      .then(setPersona)
      .catch(() => setPersona({ loaded: false }));
  }, []);

  if (!persona) return null;
  if (!persona.loaded) {
    return (
      <div className="persona-badge persona-badge--empty">
        No persona loaded
      </div>
    );
  }

  return (
    <div className="persona-badge">
      <div className="persona-badge__title">Persona loaded from soul/</div>
      <div className="persona-badge__row">
        <span>SOUL.md</span>
        <span>{persona.soul_chars} chars</span>
      </div>
      <div className="persona-badge__row">
        <span>STYLE.md</span>
        <span>{persona.style_chars} chars</span>
      </div>
      <div className="persona-badge__row">
        <span>AGENTS.md</span>
        <span>{persona.agents_chars} chars</span>
      </div>
      <div className="persona-badge__row persona-badge__row--total">
        <span>Total prompt</span>
        <span>{persona.total_chars} chars</span>
      </div>
    </div>
  );
}

// ── Dark mode hook ──

function useDarkMode() {
  const [dark, setDark] = useState(() => {
    if (typeof window !== "undefined") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    return false;
  });

  useEffect(() => {
    document.documentElement.setAttribute(
      "data-theme",
      dark ? "dark" : "light",
    );
  }, [dark]);

  return [dark, () => setDark((d) => !d)] as const;
}

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
      {sidebarOpen && (
        <div className="lci-mini-sidebar">
          <SessionSidebar />
          <PersonaBadge />
        </div>
      )}
      <ChatPanel
        title="LCI Mini"
        suggestions={SUGGESTIONS}
        placeholder="Tanya apa saja tentang LCI/LCA atau PROPER 2025..."
        greeting="Halo, saya Lici — LCI Consultant Assistant"
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
