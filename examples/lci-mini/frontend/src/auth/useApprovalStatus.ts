/**
 * useApprovalStatus — gates the app behind backend approval.
 *
 * After Firebase sign-in resolves, we hit ``/auth/me`` once to confirm
 * the backend accepts us:
 *
 * - **200** → user is approved; the app can render normally.
 * - **403 { detail: "pending_approval" }** → first-time sign-in,
 *   admin hasn't enabled the account in Firebase Console yet.
 * - **401 { detail: "account_disabled" }** → admin banned this user
 *   (Firebase Console → Disable account).
 * - Anything else (network error, 500) → treat as approved so a
 *   transient backend blip doesn't lock users out; the chat endpoints
 *   will fail loudly on their own.
 *
 * The check re-runs whenever ``auth.user`` changes so signing out +
 * back in refreshes the status.
 */

import { useEffect, useState } from "react";
import type { UseAuthReturn } from "./useAuth";

export type ApprovalStatus = "loading" | "approved" | "pending" | "disabled";

export interface UseApprovalStatusReturn {
  status: ApprovalStatus;
  /** The 401/403 detail string surfaced by the backend, if any. */
  detail: string | null;
}

export function useApprovalStatus(auth: UseAuthReturn): UseApprovalStatusReturn {
  const [status, setStatus] = useState<ApprovalStatus>("loading");
  const [detail, setDetail] = useState<string | null>(null);

  useEffect(() => {
    if (!auth.configured) {
      // No Firebase wired — approval gate is a no-op.
      setStatus("approved");
      return;
    }
    if (auth.loading) {
      setStatus("loading");
      return;
    }
    if (!auth.user) {
      // Not signed in — caller (AuthGate) shows the sign-in screen.
      setStatus("approved");
      return;
    }

    let cancelled = false;
    setStatus("loading");
    setDetail(null);

    (async () => {
      try {
        const token = await auth.getIdToken();
        const headers: Record<string, string> = {};
        if (token) headers.Authorization = `Bearer ${token}`;
        const resp = await fetch("/auth/me", { headers });
        if (cancelled) return;

        if (resp.ok) {
          setStatus("approved");
          return;
        }

        // Parse detail for both 401 and 403 cases.
        let parsedDetail: string | null = null;
        try {
          const body = await resp.json();
          if (typeof body?.detail === "string") parsedDetail = body.detail;
        } catch {
          // Non-JSON body — leave detail null.
        }

        if (resp.status === 403 && parsedDetail === "pending_approval") {
          setStatus("pending");
          setDetail(parsedDetail);
          return;
        }
        if (resp.status === 401 && parsedDetail === "account_disabled") {
          setStatus("disabled");
          setDetail(parsedDetail);
          return;
        }

        // Unrecognised error — don't lock the user out over a transient
        // blip. The actual chat request will surface the real issue.
        console.warn(
          "[useApprovalStatus] /auth/me returned",
          resp.status,
          parsedDetail,
          "- treating as approved",
        );
        setStatus("approved");
      } catch (err) {
        if (cancelled) return;
        console.warn("[useApprovalStatus] /auth/me fetch failed:", err);
        setStatus("approved");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [auth.configured, auth.loading, auth.user, auth.getIdToken]);

  return { status, detail };
}
