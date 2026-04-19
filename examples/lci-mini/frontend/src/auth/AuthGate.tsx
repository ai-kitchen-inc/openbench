/**
 * Sign-in gate — Google-only.
 *
 * Four states:
 *   1. Firebase not configured       → "setup required" screen (unless
 *                                       `requireConfigured={false}`).
 *   2. Configured + loading          → spinner.
 *   3. Configured + signed-out       → Google sign-in button.
 *   4. Configured + signed-in        → renders children.
 */

import type { ReactNode } from "react";
import { useState } from "react";
import { toFriendlyAuthError } from "./authErrors";
import { useOptionalToast } from "./Toast";
import { useApprovalStatus } from "./useApprovalStatus";
import type { UseAuthReturn } from "./useAuth";


interface AuthGateProps {
  auth: UseAuthReturn;
  children: ReactNode;
  /**
   * When true (default), blocks children behind a setup screen if
   * Firebase env vars aren't set. Set to false only for legacy
   * dev-no-auth deployments.
   */
  requireConfigured?: boolean;
}


export function AuthGate({ auth, children, requireConfigured = true }: AuthGateProps) {
  const approval = useApprovalStatus(auth);

  if (!auth.configured) {
    return requireConfigured ? <NotConfiguredScreen /> : <>{children}</>;
  }
  if (auth.loading) return <AuthLoading />;
  if (!auth.user) return <SignInScreen auth={auth} />;
  // At this point Firebase says we're signed in. Consult the backend
  // approval gate before rendering the app shell.
  if (approval.status === "loading") return <AuthLoading />;
  if (approval.status === "pending") return <PendingApprovalScreen auth={auth} />;
  if (approval.status === "disabled") return <AccountDisabledScreen auth={auth} />;
  return <>{children}</>;
}


// ---------------------------------------------------------------------------
// States
// ---------------------------------------------------------------------------


function AuthLoading() {
  return (
    <div className="auth-gate auth-gate--loading">
      <div className="auth-gate__spinner" aria-hidden="true" />
      <div>Checking sign-in…</div>
    </div>
  );
}


function NotConfiguredScreen() {
  return (
    <div className="auth-gate">
      <div className="auth-gate__panel">
        <div className="auth-gate__icon" aria-hidden="true">
          <svg
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        </div>
        <h1 className="auth-gate__title">Sign-in not configured</h1>
        <p className="auth-gate__blurb">
          This deployment requires Firebase Auth. Set the following
          environment variables and restart:
        </p>
        <pre className="auth-gate__code">
{`VITE_FIREBASE_API_KEY=…
VITE_FIREBASE_AUTH_DOMAIN=…
VITE_FIREBASE_PROJECT_ID=…`}
        </pre>
        <p className="auth-gate__blurb">
          Check <code>examples/lci-mini/.env.example</code> for all
          available env vars.
        </p>
      </div>
    </div>
  );
}


function SignInScreen({ auth }: { auth: UseAuthReturn }) {
  const toast = useOptionalToast();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleGoogle = async () => {
    if (busy) return;
    setErr(null);
    setBusy(true);
    try {
      await auth.signIn();
    } catch (caught) {
      const friendly = toFriendlyAuthError(caught);
      setErr(friendly.message);
      toast.show(friendly.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-gate">
      <div className="auth-gate__panel">
        <div className="auth-gate__icon" aria-hidden="true">
          <svg
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 2a5 5 0 0 0-5 5v4a5 5 0 0 0 10 0V7a5 5 0 0 0-5-5Z" />
            <path d="M12 16v4" />
            <path d="M8 20h8" />
          </svg>
        </div>
        <h1 className="auth-gate__title">LCI Mini</h1>
        <p className="auth-gate__blurb">
          Sign in with Google to chat with Lici. Your sessions stay
          private to your account.
        </p>

        {err && (
          <div className="auth-gate__error" role="alert">
            {err}
          </div>
        )}

        <button
          type="button"
          className="auth-gate__signin"
          onClick={handleGoogle}
          disabled={busy}
        >
          <GoogleIcon />
          <span>{busy ? "Signing in…" : "Continue with Google"}</span>
        </button>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Approval gate screens — shown after Firebase sign-in but before app access
// ---------------------------------------------------------------------------


function PendingApprovalScreen({ auth }: { auth: UseAuthReturn }) {
  return (
    <div className="auth-gate">
      <div className="auth-gate__panel">
        <div className="auth-gate__icon" aria-hidden="true">
          <svg
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 15 14" />
          </svg>
        </div>
        <h1 className="auth-gate__title">Waiting for approval</h1>
        <p className="auth-gate__blurb">
          Your account{" "}
          {auth.user?.email ? (
            <strong>{auth.user.email}</strong>
          ) : (
            "is"
          )}{" "}
          was created and is waiting for an admin to approve access.
        </p>
        <p className="auth-gate__blurb">
          Please contact the admin. You'll be able to sign in once your
          account is enabled.
        </p>
        <button
          type="button"
          className="auth-gate__link auth-gate__link--center"
          onClick={() => auth.signOut()}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}


function AccountDisabledScreen({ auth }: { auth: UseAuthReturn }) {
  return (
    <div className="auth-gate">
      <div className="auth-gate__panel">
        <div className="auth-gate__icon" aria-hidden="true">
          <svg
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
          </svg>
        </div>
        <h1 className="auth-gate__title">Account disabled</h1>
        <p className="auth-gate__blurb">
          {auth.user?.email ? (
            <>
              Access for <strong>{auth.user.email}</strong> has been
              disabled by the admin.
            </>
          ) : (
            "This account has been disabled by the admin."
          )}
        </p>
        <p className="auth-gate__blurb">Contact support to restore access.</p>
        <button
          type="button"
          className="auth-gate__link auth-gate__link--center"
          onClick={() => auth.signOut()}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}


function GoogleIcon() {
  return (
    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}
