import "@openbench/chat-ui/styles/chat-ui.css";
import "@openbench/chat-ui/styles/bundle.css";
import { AdminShell } from "./admin/AdminShell";
import { AuthGate } from "./auth/AuthGate";
import { UserChat } from "./chat/UserChat";
import { PublicDashboardPage } from "./dashboard/PublicDashboardPage";
import { matchPublicDashboardRoute } from "./dashboard/publicRoute";
import { EmbedChat } from "./embed/EmbedChat";
import { matchEmbedRoute } from "./embed/embedRoute";
import { ErrorBoundary } from "./ErrorBoundary";
import { ToastProvider } from "./Toast";
import "./global.css";

export default function App() {
  // /embed/<agentId>?key=… is the only route outside the auth gate: the
  // agent's embed key is the credential, not a Google sign-in.
  // /d/<id> is the shareable live dashboard page: public by unguessable id,
  // the backend only serves records flagged public (see /d/{id}/data).
  const publicDashboard = matchPublicDashboardRoute(window.location);
  if (publicDashboard) {
    return (
      <ErrorBoundary region="dasbor publik">
        <PublicDashboardPage dashboardId={publicDashboard.dashboardId} />
      </ErrorBoundary>
    );
  }

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
