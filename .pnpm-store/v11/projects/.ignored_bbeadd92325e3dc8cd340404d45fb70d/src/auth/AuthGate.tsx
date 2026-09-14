import { onAuthStateChanged, signInWithPopup, signOut, type User } from "firebase/auth";
import { useEffect, useState, type ReactNode } from "react";
import { setAuthTokenProvider } from "../api";
import { AccessDeniedError, fetchMe, readErrorMessage, type Me } from "../account/api";
import { BrandMark } from "../brand/BrandMark";
import { getFirebaseAuth, googleProvider, isFirebaseConfigured } from "../firebase";
import { APP_NAME, APP_TAGLINE, COMMON } from "../i18n/id";
import { useToast } from "../Toast";

type AuthzState =
  | { status: "checking" }
  | { status: "authorized"; me: Me }
  | { status: "denied"; detail: string }
  | { status: "error" };

function AuthScreen({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="auth-screen">
      <div className="auth-panel">
        <div className="brand-lockup">
          <BrandMark size={36} />
          <span className="brand-lockup__text">
            <span className="brand-lockup__name">{title}</span>
            <span className="brand-lockup__tagline">{APP_TAGLINE}</span>
          </span>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Firebase Google sign-in gate. Renders `children(me, user, signOut)` once
 * the signed-in account has been confirmed against `GET /account/me`
 * (200 = allowed, 403 = not granted, otherwise = retryable error).
 *
 * Local-dev bypass: with no VITE_FIREBASE_* config, the gate probes
 * `/account/me` without a token — a backend running with
 * OPENBENCH_AUTH_DISABLED answers as the local admin, so the app works
 * with zero auth setup (`user` is null in that mode). */
export function AuthGate({
  children,
}: {
  children: (me: Me, user: User | null, onSignOut: () => void) => ReactNode;
}) {
  const toast = useToast();
  const localMode = !isFirebaseConfigured();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [authz, setAuthz] = useState<AuthzState>({ status: "checking" });
  const [probeNonce, setProbeNonce] = useState(0);

  useEffect(() => {
    if (localMode) {
      setIsLoading(false);
      return;
    }

    const auth = getFirebaseAuth();
    return onAuthStateChanged(
      auth,
      (nextUser) => {
        setUser(nextUser);
        setIsLoading(false);
      },
      (authError) => {
        setError(authError.message);
        setIsLoading(false);
      },
    );
  }, [localMode]);

  useEffect(() => {
    if (!user) {
      setAuthTokenProvider(null);
      return;
    }
    setAuthTokenProvider(() => user.getIdToken());
    return () => setAuthTokenProvider(null);
  }, [user]);

  // Probe /account/me to confirm this signed-in account has been granted
  // access. Firebase admits any Google account, so authorization is decided
  // server-side: 200 = allowed (payload carries role + capabilities),
  // 403 = not granted, anything else (network/401/5xx) = could not verify
  // -> offer a retry.
  useEffect(() => {
    if (!user && !localMode) return;
    let cancelled = false;
    setAuthz({ status: "checking" });
    (async () => {
      try {
        const me = await fetchMe();
        if (cancelled) return;
        if (me) {
          setAuthz({ status: "authorized", me });
        } else {
          setAuthz({ status: "error" });
        }
      } catch (probeError) {
        if (cancelled) return;
        if (probeError instanceof AccessDeniedError) {
          setAuthz({ status: "denied", detail: probeError.message });
        } else {
          setAuthz({ status: "error" });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, localMode, probeNonce]);

  const handleSignIn = async () => {
    setError("");
    try {
      await signInWithPopup(getFirebaseAuth(), googleProvider);
    } catch (signInError) {
      setError(readErrorMessage(signInError));
    }
  };

  const handleSignOut = async () => {
    if (localMode) {
      toast.show("Mode lokal: tidak ada sesi untuk keluar.", "success");
      return;
    }
    try {
      await signOut(getFirebaseAuth());
      toast.show("Berhasil keluar", "success");
    } catch (signOutError) {
      toast.show(`Gagal keluar: ${readErrorMessage(signOutError)}`, "error");
    }
  };

  if (isLoading) {
    return (
      <AuthScreen title={APP_NAME}>
        <div className="auth-copy">Memeriksa autentikasi...</div>
      </AuthScreen>
    );
  }

  if (!user && !localMode) {
    return (
      <AuthScreen title={APP_NAME}>
        <div className="auth-copy">Masuk dengan akun Google yang telah disetujui untuk melanjutkan.</div>
        {error && <div className="auth-error">{error}</div>}
        <button type="button" className="auth-primary" onClick={() => void handleSignIn()}>
          Masuk dengan Google
        </button>
      </AuthScreen>
    );
  }

  if (authz.status === "checking") {
    return (
      <AuthScreen title={APP_NAME}>
        <div className="auth-copy">Memeriksa akses...</div>
      </AuthScreen>
    );
  }

  if (authz.status === "denied") {
    return (
      <AuthScreen title="Akses belum diberikan">
        <div className="auth-copy">
          Akun ini belum diberi akses ({user?.email ?? "tanpa email"}). Minta administrator
          menambahkan email Anda, lalu masuk kembali.
        </div>
        {authz.detail && <div className="auth-error">{authz.detail}</div>}
        <button type="button" className="auth-primary" onClick={() => void handleSignOut()}>
          {COMMON.signOut}
        </button>
      </AuthScreen>
    );
  }

  if (authz.status === "error") {
    return (
      <AuthScreen title={APP_NAME}>
        <div className="auth-copy">
          Tidak dapat memverifikasi akses. Periksa koneksi Anda, lalu coba lagi.
        </div>
        <button
          type="button"
          className="auth-primary"
          onClick={() => setProbeNonce((value) => value + 1)}
        >
          {COMMON.retry}
        </button>
        <button type="button" className="auth-signout" onClick={() => void handleSignOut()}>
          {COMMON.signOut}
        </button>
      </AuthScreen>
    );
  }

  return <>{children(authz.me, user, () => void handleSignOut())}</>;
}
