import { useDarkMode, ThemeIcon } from "../theme";
import type { AuthUser } from "../api";
import { SourcesSection } from "./SourcesSection";

export function ControlPanel({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  const [dark, toggleDark] = useDarkMode();

  return (
    <div className="control-panel">
      <header className="control-panel__header">
        <div className="control-panel__brand">
          <span>Controlled Source Chat</span>
          <span className="control-panel__brand-sub">Admin control panel</span>
        </div>
        <div className="control-panel__actions">
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
      </main>
    </div>
  );
}
