/**
 * React auth hook for lci-mini.
 *
 * Wraps Firebase Auth's user lifecycle in an ergonomic React API:
 *
 * - ``user``                 — current signed-in user (or null)
 * - ``loading``              — true while Firebase resolves the initial state
 * - ``configured``           — mirrors :const:`isFirebaseConfigured`
 * - ``signIn``               — Google popup sign-in (redirect fallback on popup block)
 * - ``signInWithEmail``      — email + password sign-in
 * - ``signUpWithEmail``      — create account with email + password (auto-sends verification email)
 * - ``sendPasswordReset``    — send password reset email
 * - ``resendVerification``   — re-send email verification to current user
 * - ``signOut``              — clear the Firebase session
 * - ``getIdToken``           — current ID token (refreshed if expired), or null
 *
 * All error paths are normalised through :func:`toFriendlyAuthError` so
 * the UI can display user-friendly messages without branching on raw
 * Firebase error codes.
 *
 * When Firebase is NOT configured (no VITE_FIREBASE_API_KEY), this hook
 * returns a stable "null user, configured=false" state so callers can
 * render the app as though sign-in were disabled.
 */

import {
  createUserWithEmailAndPassword,
  signOut as fbSignOut,
  getRedirectResult,
  onIdTokenChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  type User,
  type UserCredential,
} from "firebase/auth";
import { useCallback, useEffect, useRef, useState } from "react";
import { isPopupBlocked, toFriendlyAuthError } from "./authErrors";
import { getFirebaseAuth, googleProvider, isFirebaseConfigured } from "./firebaseConfig";

export interface UseAuthReturn {
  /** Current Firebase user, or null if signed out / not configured. */
  user: User | null;
  /** True while Firebase is still resolving the initial auth state. */
  loading: boolean;
  /** Whether Firebase is configured at all (env vars present). */
  configured: boolean;
  /** Trigger Google sign-in (popup → redirect fallback if blocked). */
  signIn: () => Promise<void>;
  /** Sign in with email + password. */
  signInWithEmail: (email: string, password: string) => Promise<void>;
  /**
   * Create an account with email + password.
   * Automatically sends a verification email on success.
   */
  signUpWithEmail: (email: string, password: string) => Promise<void>;
  /** Send a password reset email to ``email``. */
  sendPasswordReset: (email: string) => Promise<void>;
  /**
   * Re-send the verification email to the currently signed-in user.
   * Throws if no user is signed in, or if the user is already verified.
   */
  resendVerification: () => Promise<void>;
  /** Sign the current user out. */
  signOut: () => Promise<void>;
  /** Return the current ID token (refreshed if expired), or null. */
  getIdToken: () => Promise<string | null>;
}

function _requireAuth() {
  const auth = getFirebaseAuth();
  if (!auth) {
    const err = new Error(
      "Firebase is not configured. Set VITE_FIREBASE_API_KEY + VITE_FIREBASE_AUTH_DOMAIN + VITE_FIREBASE_PROJECT_ID in .env to enable sign-in.",
    ) as Error & { code: string };
    err.code = "auth/not-configured";
    throw err;
  }
  return auth;
}

export function useAuth(): UseAuthReturn {
  const [user, setUser] = useState<User | null>(null);
  // Only "loading" while Firebase is actually configured; otherwise
  // the caller can render immediately with a null user.
  const [loading, setLoading] = useState<boolean>(isFirebaseConfigured);
  // Keep a mutable ref on the user so getIdToken() doesn't capture a
  // stale closure.
  const userRef = useRef<User | null>(null);

  useEffect(() => {
    if (!isFirebaseConfigured) return;
    const auth = getFirebaseAuth();
    if (!auth) {
      setLoading(false);
      return;
    }
    // If we came back from a signInWithRedirect, consume the result so
    // Firebase commits the pending session. onIdTokenChanged fires
    // right after anyway; this call is just about propagating errors.
    getRedirectResult(auth).catch((err: unknown) => {
      console.error("[useAuth] getRedirectResult failed:", err);
    });
    const unsub = onIdTokenChanged(auth, (u) => {
      userRef.current = u;
      setUser(u);
      setLoading(false);
    });
    return unsub;
  }, []);

  const signIn = useCallback(async () => {
    const auth = _requireAuth();
    try {
      await signInWithPopup(auth, googleProvider);
    } catch (err: unknown) {
      const friendly = toFriendlyAuthError(err);
      if (isPopupBlocked(friendly.code)) {
        // Browser blocked the popup — fall back to redirect. The
        // user will come back to this origin; getRedirectResult() in
        // the effect above consumes the result.
        try {
          await signInWithRedirect(auth, googleProvider);
          return;
        } catch (redirectErr: unknown) {
          throw toFriendlyAuthError(redirectErr);
        }
      }
      throw friendly;
    }
  }, []);

  const signInWithEmail = useCallback(async (email: string, password: string) => {
    const auth = _requireAuth();
    try {
      await signInWithEmailAndPassword(auth, email, password);
    } catch (err: unknown) {
      throw toFriendlyAuthError(err);
    }
  }, []);

  const signUpWithEmail = useCallback(async (email: string, password: string) => {
    const auth = _requireAuth();
    let cred: UserCredential;
    try {
      cred = await createUserWithEmailAndPassword(auth, email, password);
    } catch (err: unknown) {
      throw toFriendlyAuthError(err);
    }
    // Best-effort verification email. If it fails (offline, quota),
    // don't block the sign-up — the UI can offer a "resend" button.
    try {
      await sendEmailVerification(cred.user);
    } catch (err: unknown) {
      console.warn("[useAuth] sendEmailVerification failed:", err);
    }
  }, []);

  const sendPasswordReset = useCallback(async (email: string) => {
    const auth = _requireAuth();
    try {
      await sendPasswordResetEmail(auth, email);
    } catch (err: unknown) {
      throw toFriendlyAuthError(err);
    }
  }, []);

  const resendVerification = useCallback(async () => {
    const current = userRef.current;
    if (!current) {
      const err = new Error("You must be signed in to resend verification.") as Error & {
        code: string;
      };
      err.code = "auth/not-signed-in";
      throw err;
    }
    if (current.emailVerified) {
      const err = new Error("Your email is already verified.") as Error & { code: string };
      err.code = "auth/already-verified";
      throw err;
    }
    try {
      await sendEmailVerification(current);
    } catch (err: unknown) {
      throw toFriendlyAuthError(err);
    }
  }, []);

  const signOut = useCallback(async () => {
    const auth = getFirebaseAuth();
    if (!auth) return;
    await fbSignOut(auth);
  }, []);

  const getIdToken = useCallback(async () => {
    const u = userRef.current;
    if (!u) return null;
    try {
      return await u.getIdToken();
    } catch (err) {
      console.error("[useAuth] getIdToken failed:", err);
      return null;
    }
  }, []);

  return {
    user,
    loading,
    configured: isFirebaseConfigured,
    signIn,
    signInWithEmail,
    signUpWithEmail,
    sendPasswordReset,
    resendVerification,
    signOut,
    getIdToken,
  };
}
