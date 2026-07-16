import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import { AdminShell } from "./admin/AdminShell";
import { AuthGate } from "./auth/AuthGate";
import { UserChat } from "./chat/UserChat";
import { ErrorBoundary } from "./ErrorBoundary";
import { ToastProvider } from "./Toast";
import "./global.css";

export default function App() {
  return (
    <ToastProvider>
      <ErrorBoundary region="aplikasi">
        <AuthGate>
          {(me, user, onSignOut) =>
            me.role === "admin" ? (
              <ErrorBoundary region="panel admin">
                <AdminShell me={me} user={user} onSignOut={onSignOut} />
              </ErrorBoundary>
            ) : (
              <ErrorBoundary region="percakapan">
                <UserChat me={me} user={user} onSignOut={onSignOut} />
              </ErrorBoundary>
            )
          }
        </AuthGate>
      </ErrorBoundary>
    </ToastProvider>
  );
}
