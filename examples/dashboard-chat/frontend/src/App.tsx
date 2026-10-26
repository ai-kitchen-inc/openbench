import { useCallback, useEffect, useState } from "react";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import {
  fetchMe,
  getDbStatus,
  logout,
  type AuthUser,
  type DbStatus,
} from "./api";
import { ChatSidePane } from "./chat/ChatSidePane";
import { DashboardCanvas } from "./dashboard/DashboardCanvas";
import { LoginGate } from "./LoginGate";
import { ConnectCard } from "./onboarding/ConnectCard";
import { Topbar } from "./Topbar";
import "./global.css";

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void fetchMe()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .finally(() => {
        if (!cancelled) setIsChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSignOut = () => {
    void logout();
    setUser(null);
  };

  if (isChecking) {
    return <div className="app-loading">Loading…</div>;
  }
  if (!user) {
    return <LoginGate onLogin={setUser} />;
  }
  return <Workspace key={user.username} user={user} onSignOut={handleSignOut} />;
}

/** Signed-in shell: onboarding when no DB, otherwise canvas + chat pane. */
function Workspace({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  const [dbStatus, setDbStatus] = useState<DbStatus | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  // Bumped after every finished chat turn → canvas refetches the spec.
  const [refreshTick, setRefreshTick] = useState(0);
  // Bumped by the topbar refresh button → every panel re-runs its query.
  const [dataTick, setDataTick] = useState(0);
  // True while the assistant streams a turn — canvas shows build progress.
  const [assistantBusy, setAssistantBusy] = useState(false);

  const reloadDbStatus = useCallback(() => {
    void getDbStatus()
      .then(setDbStatus)
      .catch(() => setDbStatus({ connected: false }));
  }, []);

  useEffect(reloadDbStatus, [reloadDbStatus]);

  const handleTurnComplete = useCallback(() => {
    setRefreshTick((tick) => tick + 1);
  }, []);

  const handleRefresh = useCallback(() => {
    setDataTick((tick) => tick + 1);
  }, []);

  if (dbStatus === null) {
    return <div className="app-loading">Loading…</div>;
  }

  if (!dbStatus.connected) {
    return (
      <div className="app-shell">
        <Topbar
          user={user}
          dbStatus={dbStatus}
          chatOpen={false}
          onToggleChat={null}
          onSignOut={onSignOut}
          onDisconnect={null}
          onRefresh={null}
        />
        <main className="onboarding">
          <ConnectCard onConnected={reloadDbStatus} />
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Topbar
        user={user}
        dbStatus={dbStatus}
        chatOpen={chatOpen}
        onToggleChat={() => setChatOpen((open) => !open)}
        onSignOut={onSignOut}
        onDisconnect={reloadDbStatus}
        onRefresh={handleRefresh}
      />
      <div className="workspace">
        <main className="workspace__canvas">
          <DashboardCanvas
            refreshTick={refreshTick}
            dataTick={dataTick}
            assistantBusy={assistantBusy}
          />
        </main>
        <aside
          className={`workspace__chat ${chatOpen ? "workspace__chat--open" : "workspace__chat--closed"}`}
        >
          <ChatSidePane
            user={user}
            onTurnComplete={handleTurnComplete}
            onStreamingChange={setAssistantBusy}
          />
        </aside>
      </div>
    </div>
  );
}
