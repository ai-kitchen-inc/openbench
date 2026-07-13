import { useState } from "react";
import { useDarkMode, ThemeIcon } from "../theme";
import type { AuthUser } from "../api";
import { McpCatalogPanel } from "../mcp-catalog/McpCatalogPanel";
import { SourcesSection } from "./SourcesSection";
import { TestChatDock } from "./TestChatDock";
import { UsersSection } from "./UsersSection";

export function ControlPanel({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  const [dark, toggleDark] = useDarkMode();
  const [mcpCatalogOpen, setMcpCatalogOpen] = useState(false);
  // Open by default so the admin lands with a live preview of the guest experience;
  // it docks beside the settings (not a modal), so it never blocks editing.
  const [testChatOpen, setTestChatOpen] = useState(true);

  return (
    <div className="control-panel">
      <header className="control-panel__header">
        <div className="control-panel__brand">
          <span className="control-panel__brand-icon">
            <BrandIcon />
          </span>
          <span className="control-panel__brand-text">
            <span>Controlled Source Chat</span>
            <span className="control-panel__brand-sub">Admin control panel</span>
          </span>
        </div>
        <div className="control-panel__actions">
          <button
            type="button"
            className={`panel-button${testChatOpen ? "" : " panel-button--primary"}`}
            onClick={() => setTestChatOpen((open) => !open)}
          >
            {testChatOpen ? "Hide test chat" : "Test chat"}
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
      </header>
      <div className="control-panel__main">
        <main className="control-panel__body">
          <SourcesSection />
          <section className="panel-section" aria-label="MCP servers">
            <div className="panel-section__header">
              <div>
                <div className="panel-section__title">
                  <McpIcon />
                  MCP servers
                </div>
                <div className="panel-section__subtitle">
                  Tools the assistant may call during chats. Tool results count as citable
                  sources.
                </div>
              </div>
              <button
                type="button"
                className="panel-button"
                onClick={() => setMcpCatalogOpen(true)}
              >
                Manage MCP servers
              </button>
            </div>
          </section>
          <UsersSection currentUsername={user.username} />
        </main>
        {testChatOpen && <TestChatDock onClose={() => setTestChatOpen(false)} />}
      </div>
      <McpCatalogPanel open={mcpCatalogOpen} onClose={() => setMcpCatalogOpen(false)} />
    </div>
  );
}

function BrandIcon() {
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
      <line x1="21" y1="4" x2="14" y2="4" />
      <line x1="10" y1="4" x2="3" y2="4" />
      <line x1="21" y1="12" x2="12" y2="12" />
      <line x1="8" y1="12" x2="3" y2="12" />
      <line x1="21" y1="20" x2="16" y2="20" />
      <line x1="12" y1="20" x2="3" y2="20" />
      <line x1="14" y1="2" x2="14" y2="6" />
      <line x1="8" y1="10" x2="8" y2="14" />
      <line x1="16" y1="18" x2="16" y2="22" />
    </svg>
  );
}

function McpIcon() {
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
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  );
}
