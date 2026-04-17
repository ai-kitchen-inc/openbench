/**
 * React auth hook for lci-mini.
 *
 * Wraps Firebase Auth's user lifecycle in an ergonomic React API:
 *
 * - ``user``          — current signed-in user (or null)
 * - ``loading``       — true while Firebase resolves the initial state
 * - ``signIn``        — trigger Google popup sign-in
 * - ``signOut``       — clear the Firebase session
 * - ``getIdToken``    — async function returning the current ID token,
 *                       suitable for ChatConfig.getAuthToken
 * - ``configured``    — mirrors :const:`isFirebaseConfigured` so
 *                       callers can gate UI on "is auth turned on?"
 *
 * When Firebase is NOT configured (no VITE_FIREBASE_API_KEY), this
 * hook returns a stable "null user, configured=false" state — callers
 * render the app as though sign-in were disabled.
 */

import {
  type User,
  onIdTokenChanged,
  signInWithPopup,
  signOut as fbSignOut,
} from "firebase/auth";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getFirebaseAuth,
  googleProvider,
  isFirebaseConfigured,
} from "./firebaseConfig";

export interface UseAuthReturn {
  /** Current Firebase user, or null if signed out / not configured. */
  user: User | null;
  /** True while Firebase is still resolving the initial auth state. */
  loading: boolean;
  /** Whether Firebase is configured at all (env vars present). */
  configured: boolean;
  /** Trigger Google sign-in via popup. */
  signIn: () => Promise<void>;
  /** Sign the current user out. */
  signOut: () => Promise<void>;
  /** Return the current ID token (refreshed if expired), or null. */
  getIdToken: () => Promise<string | null>;
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
    const unsub = onIdTokenChanged(auth, (u) => {
      userRef.current = u;
      setUser(u);
      setLoading(false);
    });
    return unsub;
  }, []);

  const signIn = useCallback(async () => {
    const auth = getFirebaseAuth();
    if (!auth) {
      throw new Error(
        "Firebase is not configured. Set VITE_FIREBASE_API_KEY + VITE_FIREBASE_AUTH_DOMAIN + VITE_FIREBASE_PROJECT_ID in .env to enable sign-in.",
      );
    }
    await signInWithPopup(auth, googleProvider);
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
