import { useEffect, useState } from "react";
import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import { fetchMe, logout, type AuthUser } from "./api";
import { BrandMark } from "./brand/BrandMark";
import { AdminShell } from "./control-panel/AdminShell";
import { ErrorBoundary } from "./ErrorBoundary";
import { GuestChat } from "./guest/GuestChat";
import { LoginGate } from "./LoginGate";
import { ToastProvider } from "./Toast";
import "./global.css";

export default function App() {
  return (
    <ToastProvider>
      <ErrorBoundary region="aplikasi">
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
    return (
      <div className="app-loading">
        <BrandMark size={48} />
        <span>Memuat aplikasi...</span>
      </div>
    );
  }
  if (!user) {
    return <LoginGate onLogin={setUser} />;
  }
  return <SignedInApp user={user} onSignOut={handleSignOut} />;
}

function SignedInApp({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  if (user.role === "admin") {
    return (
      <ErrorBoundary region="panel admin">
        <AdminShell user={user} onSignOut={onSignOut} />
      </ErrorBoundary>
    );
  }
  return (
    <ErrorBoundary region="percakapan">
      <GuestChat user={user} onSignOut={onSignOut} />
    </ErrorBoundary>
  );
}
