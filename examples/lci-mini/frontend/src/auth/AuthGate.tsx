/**
 * Sign-in gate.
 *
 * Renders a full-screen auth screen when Firebase is configured AND
 * the user is signed out. Three views ("sign-in", "register",
 * "forgot") are toggled locally — this component owns its own tab
 * state so the rest of the app doesn't need to know.
 *
 * Passes through (renders children) when:
 *   - the user is signed in, OR
 *   - Firebase isn't configured at all (dev / no-auth deployments).
 *
 * If the user is signed in but their email isn't verified, a banner
 * above the children offers a "Resend verification email" button.
 */

import { type FormEvent, type ReactNode, useState } from "react";
import { toFriendlyAuthError } from "./authErrors";
import { useOptionalToast } from "./Toast";
import type { UseAuthReturn } from "./useAuth";

interface AuthGateProps {
  auth: UseAuthReturn;
  children: ReactNode;
  /** Require verified email before revealing the app. Default: false. */
  requireEmailVerified?: boolean;
}

type ViewMode = "signin" | "register" | "forgot";

export function AuthGate({ auth, children, requireEmailVerified = false }: AuthGateProps) {
  if (!auth.configured) return <>{children}</>;
  if (auth.loading) return <AuthLoading />;
  if (!auth.user) return <SignInScreen auth={auth} />;

  // User is signed in.
  const passwordUser = auth.user.providerData?.some((p) => p.providerId === "password") ?? false;
  const needsVerification = passwordUser && !auth.user.emailVerified;

  if (requireEmailVerified && needsVerification) {
    return <VerifyEmailScreen auth={auth} />;
  }

  return (
    <>
      {needsVerification && <VerifyBanner auth={auth} />}
      {children}
    </>
  );
}

// ---------------------------------------------------------------------------
// Loading splash
// ---------------------------------------------------------------------------

function AuthLoading() {
  return (
    <div className="auth-gate auth-gate--loading">
      <div className="auth-gate__spinner" aria-hidden="true" />
      <div>Checking sign-in…</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sign-in screen (tabbed)
// ---------------------------------------------------------------------------

function SignInScreen({ auth }: { auth: UseAuthReturn }) {
  const [mode, setMode] = useState<ViewMode>("signin");
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
          Sign in to chat with Lici. Your chat history and notes stay in your own Google account
          when you connect Drive later.
        </p>

        {mode === "signin" && <SignInForm auth={auth} onSwitch={setMode} />}
        {mode === "register" && <RegisterForm auth={auth} onSwitch={setMode} />}
        {mode === "forgot" && <ForgotForm auth={auth} onSwitch={setMode} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sign-in form
// ---------------------------------------------------------------------------

function SignInForm({ auth, onSwitch }: { auth: UseAuthReturn; onSwitch: (m: ViewMode) => void }) {
  const toast = useOptionalToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setErr(null);
    setBusy(true);
    try {
      await auth.signInWithEmail(email.trim(), password);
    } catch (caught) {
      const friendly = toFriendlyAuthError(caught);
      setErr(friendly.message);
      toast.show(friendly.message, "error");
    } finally {
      setBusy(false);
    }
  };

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
    <form className="auth-gate__form" onSubmit={handleSubmit} aria-label="Sign in">
      <label className="auth-gate__field">
        <span>Email</span>
        <input
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={busy}
        />
      </label>
      <label className="auth-gate__field">
        <span>Password</span>
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={busy}
        />
      </label>

      {err && (
        <div className="auth-gate__error" role="alert">
          {err}
        </div>
      )}

      <button type="submit" className="auth-gate__primary" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </button>

      <div className="auth-gate__inline-links">
        <button
          type="button"
          className="auth-gate__link"
          onClick={() => onSwitch("forgot")}
          disabled={busy}
        >
          Forgot password?
        </button>
        <button
          type="button"
          className="auth-gate__link"
          onClick={() => onSwitch("register")}
          disabled={busy}
        >
          Create account
        </button>
      </div>

      <div className="auth-gate__divider" aria-hidden="true">
        <span>or</span>
      </div>

      <button type="button" className="auth-gate__signin" onClick={handleGoogle} disabled={busy}>
        <GoogleIcon />
        <span>Sign in with Google</span>
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Register form
// ---------------------------------------------------------------------------

function RegisterForm({
  auth,
  onSwitch,
}: {
  auth: UseAuthReturn;
  onSwitch: (m: ViewMode) => void;
}) {
  const toast = useOptionalToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setErr(null);
    if (password !== confirm) {
      setErr("Passwords don't match.");
      return;
    }
    if (password.length < 6) {
      setErr("Password must be at least 6 characters.");
      return;
    }
    setBusy(true);
    try {
      await auth.signUpWithEmail(email.trim(), password);
      toast.show("Account created — check your inbox to verify.", "success");
    } catch (caught) {
      const friendly = toFriendlyAuthError(caught);
      setErr(friendly.message);
      toast.show(friendly.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="auth-gate__form" onSubmit={handleSubmit} aria-label="Register">
      <label className="auth-gate__field">
        <span>Email</span>
        <input
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={busy}
        />
      </label>
      <label className="auth-gate__field">
        <span>Password</span>
        <input
          type="password"
          autoComplete="new-password"
          required
          minLength={6}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={busy}
        />
      </label>
      <label className="auth-gate__field">
        <span>Confirm password</span>
        <input
          type="password"
          autoComplete="new-password"
          required
          minLength={6}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          disabled={busy}
        />
      </label>

      {err && (
        <div className="auth-gate__error" role="alert">
          {err}
        </div>
      )}

      <button type="submit" className="auth-gate__primary" disabled={busy}>
        {busy ? "Creating account…" : "Create account"}
      </button>

      <div className="auth-gate__inline-links auth-gate__inline-links--center">
        <button
          type="button"
          className="auth-gate__link"
          onClick={() => onSwitch("signin")}
          disabled={busy}
        >
          Already have an account? Sign in
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Forgot password form
// ---------------------------------------------------------------------------

function ForgotForm({ auth, onSwitch }: { auth: UseAuthReturn; onSwitch: (m: ViewMode) => void }) {
  const toast = useOptionalToast();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setErr(null);
    setBusy(true);
    try {
      await auth.sendPasswordReset(email.trim());
      setSent(true);
      toast.show("Password reset email sent. Check your inbox.", "success");
    } catch (caught) {
      const friendly = toFriendlyAuthError(caught);
      setErr(friendly.message);
      toast.show(friendly.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="auth-gate__form" onSubmit={handleSubmit} aria-label="Reset password">
      <p className="auth-gate__blurb">
        Enter the email address you used to register. We'll send you a link to choose a new
        password.
      </p>
      <label className="auth-gate__field">
        <span>Email</span>
        <input
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={busy || sent}
        />
      </label>

      {err && (
        <div className="auth-gate__error" role="alert">
          {err}
        </div>
      )}
      {sent && (
        <div className="auth-gate__info" role="status">
          Reset email sent. Check your inbox (and spam folder).
        </div>
      )}

      <button type="submit" className="auth-gate__primary" disabled={busy || sent}>
        {busy ? "Sending…" : sent ? "Sent" : "Send reset link"}
      </button>

      <div className="auth-gate__inline-links auth-gate__inline-links--center">
        <button
          type="button"
          className="auth-gate__link"
          onClick={() => onSwitch("signin")}
          disabled={busy}
        >
          Back to sign in
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Email verification screen (blocks app when requireEmailVerified=true)
// ---------------------------------------------------------------------------

function VerifyEmailScreen({ auth }: { auth: UseAuthReturn }) {
  const toast = useOptionalToast();
  const [busy, setBusy] = useState(false);

  const handleResend = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await auth.resendVerification();
      toast.show("Verification email sent again.", "success");
    } catch (caught) {
      const friendly = toFriendlyAuthError(caught);
      toast.show(friendly.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-gate">
      <div className="auth-gate__panel">
        <h1 className="auth-gate__title">Verify your email</h1>
        <p className="auth-gate__blurb">
          We sent a verification link to <strong>{auth.user?.email}</strong>. Click the link, then
          reload this page.
        </p>
        <button type="button" className="auth-gate__primary" onClick={handleResend} disabled={busy}>
          {busy ? "Sending…" : "Resend verification email"}
        </button>
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

// ---------------------------------------------------------------------------
// Non-blocking verification banner (default behaviour)
// ---------------------------------------------------------------------------

function VerifyBanner({ auth }: { auth: UseAuthReturn }) {
  const toast = useOptionalToast();
  const [busy, setBusy] = useState(false);

  const handleResend = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await auth.resendVerification();
      toast.show("Verification email sent.", "success");
    } catch (caught) {
      const friendly = toFriendlyAuthError(caught);
      toast.show(friendly.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-verify-banner" role="status">
      <span>
        Please verify your email <strong>{auth.user?.email}</strong> to secure your account.
      </span>
      <button
        type="button"
        className="auth-verify-banner__btn"
        onClick={handleResend}
        disabled={busy}
      >
        {busy ? "Sending…" : "Resend"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inlined Google G icon
// ---------------------------------------------------------------------------

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
