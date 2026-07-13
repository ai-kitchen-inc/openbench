import { useState } from "react";
import { useDarkMode, ThemeIcon } from "../theme";
import type { AuthUser } from "../api";
import { McpCatalogPanel } from "../mcp-catalog/McpCatalogPanel";
import { SourcesSection } from "./SourcesSection";
import { TestChatDrawer } from "./TestChatDrawer";
import { UsersSection } from "./UsersSection";

export function ControlPanel({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  const [dark, toggleDark] = useDarkMode();
  const [mcpCatalogOpen, setMcpCatalogOpen] = useState(false);
  const [testChatOpen, setTestChatOpen] = useState(false);

  return (
    <div className="control-panel">
      <header className="control-panel__header">
        <div className="control-panel__brand">
          <span>Controlled Source Chat</span>
          <span className="control-panel__brand-sub">Admin control panel</span>
        </div>
        <div className="control-panel__actions">
          <button
            type="button"
            className="panel-button panel-button--primary"
            onClick={() => setTestChatOpen(true)}
          >
            Test chat
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
      <McpCatalogPanel open={mcpCatalogOpen} onClose={() => setMcpCatalogOpen(false)} />
      <TestChatDrawer open={testChatOpen} onClose={() => setTestChatOpen(false)} />
    </div>
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
