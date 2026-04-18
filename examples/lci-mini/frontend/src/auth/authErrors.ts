/**
 * Map Firebase Auth error codes to user-friendly messages.
 *
 * Covers every code listed under "AuthError" in the Firebase Web SDK
 * v10 docs (plus a handful of historical aliases). Anything unmapped
 * falls back to a generic message — the raw code is always preserved
 * on the returned error's ``code`` field so callers can branch.
 *
 * The returned Error carries:
 *   - ``message``    — the friendly string (English; localize later)
 *   - ``code``       — the original ``auth/xxx`` code, or "auth/unknown"
 *
 * We deliberately avoid leaking "user not found" vs "wrong password"
 * distinctions into separate messages — both become "incorrect email
 * or password" so attackers can't use the form to enumerate valid
 * accounts. Firebase itself has moved to the same convention via
 * "auth/invalid-credential" in recent SDK versions.
 */

export interface FriendlyAuthError extends Error {
  /** Original Firebase code, e.g. "auth/invalid-email". */
  code: string;
}

const FRIENDLY_MESSAGES: Record<string, string> = {
  // Bad credentials — deliberately merged so we don't enumerate accounts.
  "auth/invalid-credential": "Incorrect email or password.",
  "auth/invalid-login-credentials": "Incorrect email or password.",
  "auth/wrong-password": "Incorrect email or password.",
  "auth/user-not-found": "Incorrect email or password.",

  // Email-shape / password-shape problems.
  "auth/invalid-email": "That doesn't look like a valid email address.",
  "auth/missing-email": "Please enter an email address.",
  "auth/missing-password": "Please enter a password.",
  "auth/weak-password":
    "Password is too weak. Use at least 6 characters, and mix letters and numbers for safety.",

  // Registration collisions.
  "auth/email-already-in-use": "An account already exists for this email. Sign in instead.",

  // Account state.
  "auth/user-disabled": "This account has been disabled. Contact support.",
  "auth/requires-recent-login": "Please sign in again to complete this action.",

  // Verification.
  "auth/invalid-verification-code": "That verification code is invalid or has expired.",
  "auth/expired-action-code": "That link has expired. Request a new one.",
  "auth/invalid-action-code": "That link is invalid or has already been used.",

  // Network / rate limit.
  "auth/network-request-failed": "Network error. Check your connection and try again.",
  "auth/too-many-requests": "Too many attempts. Please wait a minute before trying again.",
  "auth/internal-error": "Something went wrong on our end. Please try again.",

  // OAuth popup flow.
  "auth/popup-closed-by-user": "Sign-in window was closed before finishing. Please try again.",
  "auth/popup-blocked": "Sign-in popup was blocked by the browser. We'll redirect instead.",
  "auth/cancelled-popup-request": "Sign-in was cancelled because another popup is already open.",
  "auth/unauthorized-domain": "This site isn't authorised to sign you in. Contact support.",

  // Provider mismatches (e.g. Google account, then email/password on same email).
  "auth/account-exists-with-different-credential":
    "An account with this email already exists using a different sign-in method. Try signing in with Google.",

  // Rare / fall-through.
  "auth/operation-not-allowed":
    "This sign-in method isn't enabled for this project. Contact support.",
  "auth/user-token-expired": "Your session has expired. Please sign in again.",
};

/**
 * Convert a thrown error (usually a FirebaseError) into a friendly one.
 *
 * Non-FirebaseError exceptions pass through unchanged (they get the
 * "auth/unknown" code so callers can still branch on ``.code``).
 */
export function toFriendlyAuthError(err: unknown): FriendlyAuthError {
  if (err && typeof err === "object" && "code" in err) {
    const code = String((err as { code: unknown }).code ?? "auth/unknown");
    const fallback =
      (err as { message?: unknown }).message instanceof String ||
      typeof (err as { message?: unknown }).message === "string"
        ? String((err as { message?: unknown }).message)
        : "Authentication failed. Please try again.";
    const message = FRIENDLY_MESSAGES[code] ?? fallback;
    const out = new Error(message) as FriendlyAuthError;
    out.code = code;
    return out;
  }
  if (err instanceof Error) {
    const out = new Error(err.message) as FriendlyAuthError;
    out.code = "auth/unknown";
    return out;
  }
  const out = new Error("Authentication failed. Please try again.") as FriendlyAuthError;
  out.code = "auth/unknown";
  return out;
}

/** True if the code matches "popup was blocked by the browser". */
export function isPopupBlocked(code: string): boolean {
  return (
    code === "auth/popup-blocked" || code === "auth/operation-not-supported-in-this-environment"
  );
}
