import { useEffect, useState } from "react";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import { fetchMe, logout, type AuthUser } from "./api";
import { ErrorBoundary } from "./ErrorBoundary";
import { LoginGate } from "./LoginGate";
import { ToastProvider } from "./Toast";
import "./global.css";

export default function App() {
  return (
    <ToastProvider>
      <ErrorBoundary region="the app">
        <AuthRoot />
      </ErrorBoundary>
    </ToastProvider>
  );
}

function AuthRoot() {
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
    return <div className="app-loading">Loading...</div>;
  }
  if (!user) {
    return <LoginGate onLogin={setUser} />;
  }
  return <SignedInApp user={user} onSignOut={handleSignOut} />;
}

function SignedInApp({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  return (
    <div className="app-loading">
      Signed in as {user.username} ({user.role}).
      <button type="button" className="auth-signout" onClick={onSignOut}>
        Sign out
      </button>
    </div>
  );
}
