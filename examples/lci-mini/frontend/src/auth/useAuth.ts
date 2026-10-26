/**
 * React auth hook for lci-mini — Google sign-in only.
 *
 * Exposes:
 *   - ``user``        — current Firebase user (or null)
 *   - ``loading``     — true while Firebase resolves the initial auth state
 *   - ``configured``  — mirrors :const:`isFirebaseConfigured`
 *   - ``signIn``      — Google popup, with redirect fallback for blocked popups
 *   - ``signOut``     — clear the Firebase session
 *   - ``getIdToken``  — current ID token (refreshed if expired), or null
 *
 * Errors are normalised through :func:`toFriendlyAuthError` so the UI
 * can surface a single human-readable string without branching on raw
 * Firebase codes.
 */

import {
  type User,
  signOut as fbSignOut,
  getRedirectResult,
  onIdTokenChanged,
  signInWithPopup,
  signInWithRedirect,
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
  const [loading, setLoading] = useState<boolean>(isFirebaseConfigured);
  // Ref avoids stale closures in getIdToken.
  const userRef = useRef<User | null>(null);

  useEffect(() => {
    if (!isFirebaseConfigured) return;
    const auth = getFirebaseAuth();
    if (!auth) {
      setLoading(false);
      return;
    }
    // Consume any pending signInWithRedirect result; onIdTokenChanged
    // fires right after this anyway. Calling it avoids silent failures
    // when the popup fallback kicked in.
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
    signOut,
    getIdToken,
  };
}
