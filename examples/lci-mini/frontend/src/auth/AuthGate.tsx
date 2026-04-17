/**
 * Sign-in gate.
 *
 * Renders a minimal "Sign in with Google" screen when Firebase is
 * configured AND the user is signed out. Passes through (renders
 * children) when the user is signed in OR when Firebase isn't
 * configured at all (dev / no-auth deployments).
 */

import type { ReactNode } from "react";
import type { UseAuthReturn } from "./useAuth";

interface AuthGateProps {
  auth: UseAuthReturn;
  children: ReactNode;
}

export function AuthGate({ auth, children }: AuthGateProps) {
  if (!auth.configured) return <>{children}</>;
  if (auth.loading) return <AuthLoading />;
  if (!auth.user) return <SignInScreen onSignIn={auth.signIn} />;
  return <>{children}</>;
}

function AuthLoading() {
  return (
    <div className="auth-gate auth-gate--loading">
      <div className="auth-gate__spinner" aria-hidden="true" />
      <div>Checking sign-in…</div>
    </div>
  );
}

function SignInScreen({ onSignIn }: { onSignIn: () => Promise<void> }) {
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
          Sign in to chat with Lici. Your chat history and notes stay in your
          own Google account when you connect Drive later.
        </p>
        <button
          type="button"
          className="auth-gate__signin"
          onClick={() => {
            onSignIn().catch((err) => {
              console.error("Sign-in failed:", err);
            });
          }}
        >
          <svg
            aria-hidden="true"
            width="18"
            height="18"
            viewBox="0 0 48 48"
          >
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
          <span>Sign in with Google</span>
        </button>
      </div>
    </div>
  );
}
