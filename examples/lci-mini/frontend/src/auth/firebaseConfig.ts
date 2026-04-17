/**
 * Firebase config + lazy app initialization for lci-mini.
 *
 * Firebase is OPTIONAL in this demo — if VITE_FIREBASE_API_KEY is
 * unset, ``isFirebaseConfigured`` returns ``false`` and the entire
 * auth layer short-circuits. The UI then renders as it did pre-auth
 * (anonymous synthetic user at the backend).
 *
 * This keeps `pnpm dev` working out-of-the-box without any Firebase
 * project, while deployments that want real sign-in set the five
 * `VITE_FIREBASE_*` env vars and get full auth.
 */

import { type FirebaseApp, getApps, initializeApp } from "firebase/app";
import { GoogleAuthProvider, type Auth, getAuth } from "firebase/auth";

interface FirebaseClientConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  appId?: string;
  messagingSenderId?: string;
  storageBucket?: string;
}

function readConfig(): FirebaseClientConfig | null {
  const apiKey = import.meta.env.VITE_FIREBASE_API_KEY?.trim();
  const authDomain = import.meta.env.VITE_FIREBASE_AUTH_DOMAIN?.trim();
  const projectId = import.meta.env.VITE_FIREBASE_PROJECT_ID?.trim();

  if (!apiKey || !authDomain || !projectId) {
    return null;
  }
  return {
    apiKey,
    authDomain,
    projectId,
    appId: import.meta.env.VITE_FIREBASE_APP_ID?.trim() || undefined,
    messagingSenderId:
      import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID?.trim() || undefined,
    storageBucket:
      import.meta.env.VITE_FIREBASE_STORAGE_BUCKET?.trim() || undefined,
  };
}

let _firebaseApp: FirebaseApp | null = null;
let _firebaseAuth: Auth | null = null;

export const firebaseConfig = readConfig();

export const isFirebaseConfigured = firebaseConfig !== null;

/**
 * Return a singleton Firebase App instance, creating it on first call.
 *
 * Safe to call repeatedly; safe to call before Firebase is configured
 * (returns null in that case so callers can short-circuit).
 */
export function getFirebaseApp(): FirebaseApp | null {
  if (!firebaseConfig) return null;
  if (_firebaseApp) return _firebaseApp;
  const existing = getApps();
  _firebaseApp = existing.length > 0 ? existing[0] : initializeApp(firebaseConfig);
  return _firebaseApp;
}

/** Return the process-wide Firebase Auth client, or null if not configured. */
export function getFirebaseAuth(): Auth | null {
  if (_firebaseAuth) return _firebaseAuth;
  const app = getFirebaseApp();
  if (!app) return null;
  _firebaseAuth = getAuth(app);
  return _firebaseAuth;
}

/** Pre-configured Google provider for ``signInWithPopup``. */
export const googleProvider = new GoogleAuthProvider();
