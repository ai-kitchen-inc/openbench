import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import { AdminShell } from "./admin/AdminShell";
import { AuthGate } from "./auth/AuthGate";
import { UserChat } from "./chat/UserChat";
import { EmbedChat } from "./embed/EmbedChat";
import { matchEmbedRoute } from "./embed/embedRoute";
import { ErrorBoundary } from "./ErrorBoundary";
import { ToastProvider } from "./Toast";
import "./global.css";

export default function App() {
  // /embed/<agentId>?key=… is the only route outside the auth gate: the
  // agent's embed key is the credential, not a Google sign-in.
  const embed = matchEmbedRoute(window.location);
  if (embed) {
    return (
      <ToastProvider>
        <ErrorBoundary region="embed">
          <EmbedChat agentId={embed.agentId} embedKey={embed.embedKey} theme={embed.theme} />
        </ErrorBoundary>
      </ToastProvider>
    );
  }

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
