/**
 * Header user badge — shows the signed-in email + a menu for
 * connect / disconnect Drive + sign out.
 *
 * Reads Drive connection state from /auth/me so the UI can render
 * "Drive connected" vs a "Connect Drive" prompt inline with the
 * sign-in display.
 */

import { useCallback, useEffect, useState } from "react";
import { useOptionalToast } from "./Toast";
import type { UseAuthReturn } from "./useAuth";

interface DriveStatus {
  /** True when the backend has Drive OAuth env vars set up. */
  configured?: boolean;
  connected: boolean;
  folderId: string | null;
  email: string | null;
}

interface AuthMeResponse {
  uid: string;
  email: string | null;
  name: string | null;
  emailVerified: boolean;
  mode: string;
  drive?: DriveStatus;
}

interface UserBadgeProps {
  auth: UseAuthReturn;
}

export function UserBadge({ auth }: UserBadgeProps) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<AuthMeResponse | null>(null);
  const toast = useOptionalToast();

  const refresh = useCallback(async () => {
    const token = await auth.getIdToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    try {
      const resp = await fetch("/auth/me", { headers });
      if (resp.ok) setStatus(await resp.json());
    } catch (err) {
      console.error("[UserBadge] /auth/me failed:", err);
    }
  }, [auth]);

  useEffect(() => {
    if (!auth.configured) return;
    refresh();
  }, [auth.configured, auth.user, refresh]);

  if (!auth.configured) return null;
  if (!auth.user) return null;

  const display = auth.user.email || auth.user.displayName || auth.user.uid;
  const driveConnected = status?.drive?.connected ?? false;
  // Drive OAuth is optional — only show the connect/disconnect menu
  // items when the backend advertises it's configured.
  const driveConfigured = status?.drive?.configured ?? false;

  const handleConnectDrive = async () => {
    const token = await auth.getIdToken();
    if (!token) return;
    try {
      const resp = await fetch("/auth/drive/connect", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) {
        console.error("connect failed:", resp.status);
        toast.show(`Couldn't start Google Drive connection (HTTP ${resp.status}).`, "error");
        return;
      }
      const { authorizeUrl } = await resp.json();
      if (authorizeUrl) window.location.href = authorizeUrl;
    } catch (err) {
      console.error("[UserBadge] connect failed:", err);
      toast.show("Couldn't reach the server for Drive connection.", "error");
    }
  };

  const handleDisconnectDrive = async () => {
    const token = await auth.getIdToken();
    if (!token) return;
    try {
      const resp = await fetch("/auth/drive/disconnect", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) {
        toast.show("Couldn't disconnect Google Drive. Try again.", "error");
        return;
      }
      await refresh();
      toast.show("Google Drive disconnected.", "success");
    } catch (err) {
      console.error("[UserBadge] disconnect failed:", err);
      toast.show("Couldn't reach the server to disconnect Drive.", "error");
    }
  };

  return (
    <div className="user-badge">
      <button
        type="button"
        className="user-badge__trigger"
        onClick={() => setOpen((o) => !o)}
        title={display}
        aria-label="Account menu"
      >
        <span className="user-badge__email">{display}</span>
        {driveConnected && <span className="user-badge__drive-dot" aria-hidden="true" />}
      </button>
      {open && (
        <div className="user-badge__menu" role="menu">
          <div className="user-badge__menu-email">{display}</div>
          <div className="user-badge__menu-sep" aria-hidden="true" />
          {driveConfigured && (
            <>
              {driveConnected ? (
                <button
                  type="button"
                  className="user-badge__menu-item"
                  onClick={() => {
                    handleDisconnectDrive();
                    setOpen(false);
                  }}
                  role="menuitem"
                >
                  Disconnect Google Drive
                </button>
              ) : (
                <button
                  type="button"
                  className="user-badge__menu-item"
                  onClick={() => {
                    handleConnectDrive();
                    setOpen(false);
                  }}
                  role="menuitem"
                >
                  Connect Google Drive
                </button>
              )}
              <div className="user-badge__menu-sep" aria-hidden="true" />
            </>
          )}
          <button
            type="button"
            className="user-badge__menu-item"
            onClick={() => {
              auth.signOut();
              setOpen(false);
            }}
            role="menuitem"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
