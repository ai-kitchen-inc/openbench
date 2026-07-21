import { Database, LayoutDashboard, LogOut, Moon, PanelRight, Sun, Unplug } from "lucide-react";
import { useState } from "react";
import { disconnectDb, type AuthUser, type DbStatus } from "./api";
import { useDarkMode } from "./theme";

export function Topbar({
  user,
  dbStatus,
  chatOpen,
  onToggleChat,
  onSignOut,
  onDisconnect,
}: {
  user: AuthUser;
  dbStatus: DbStatus;
  chatOpen: boolean;
  onToggleChat: (() => void) | null;
  onSignOut: () => void;
  onDisconnect: (() => void) | null;
}) {
  const [dark, toggleDark] = useDarkMode();
  const [busy, setBusy] = useState(false);

  const handleDisconnect = async () => {
    if (busy || !onDisconnect) return;
    if (!window.confirm("Disconnect this database? Your dashboard stays saved.")) return;
    setBusy(true);
    try {
      await disconnectDb();
      onDisconnect();
    } finally {
      setBusy(false);
    }
  };

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <LayoutDashboard size={18} strokeWidth={1.5} />
        <span>Dashboard Chat</span>
      </div>

      <div className="topbar__actions">
        {dbStatus.connected && (
          <span className="topbar__chip" title={dbStatus.urlRedacted}>
            <Database size={14} strokeWidth={1.5} />
            {dbStatus.dialect}
            {typeof dbStatus.tableCount === "number" && (
              <span className="topbar__chip-muted">{dbStatus.tableCount} tables</span>
            )}
          </span>
        )}
        {dbStatus.connected && onDisconnect && (
          <button
            type="button"
            className="topbar__icon-button"
            onClick={handleDisconnect}
            disabled={busy}
            title="Disconnect database"
            aria-label="Disconnect database"
          >
            <Unplug size={16} strokeWidth={1.5} />
          </button>
        )}
        <button
          type="button"
          className="topbar__icon-button"
          onClick={toggleDark}
          title={dark ? "Switch to light mode" : "Switch to dark mode"}
          aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {dark ? <Sun size={16} strokeWidth={1.5} /> : <Moon size={16} strokeWidth={1.5} />}
        </button>
        {onToggleChat && (
          <button
            type="button"
            className={`topbar__icon-button ${chatOpen ? "topbar__icon-button--active" : ""}`}
            onClick={onToggleChat}
            title={chatOpen ? "Hide assistant" : "Show assistant"}
            aria-label={chatOpen ? "Hide assistant" : "Show assistant"}
          >
            <PanelRight size={16} strokeWidth={1.5} />
          </button>
        )}
        <span className="topbar__user" title={`Signed in as ${user.username}`}>
          {user.username}
        </span>
        <button
          type="button"
          className="topbar__icon-button"
          onClick={onSignOut}
          title="Sign out"
          aria-label="Sign out"
        >
          <LogOut size={16} strokeWidth={1.5} />
        </button>
      </div>
    </header>
  );
}
