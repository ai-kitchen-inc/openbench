/**
 * Tests for useAuth + firebaseConfig.
 *
 * Two modes are exercised:
 * - "not configured" — env vars unset. Default for the outer `describe`.
 * - "configured"     — env vars stubbed via `vi.stubEnv`; Firebase
 *    modules are mocked so no real SDK init happens.
 *
 * The firebase/auth mock below fakes the ~10 functions we call from
 * useAuth.ts. Keeping them all in one vi.mock() factory means adding
 * new Firebase calls is one import + one mock entry.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Shared mocks for firebase/auth + firebase/app
// ---------------------------------------------------------------------------

type IdTokenCallback = (u: MockUser | null) => void;

interface MockUser {
  uid: string;
  email: string | null;
  displayName: string | null;
  emailVerified: boolean;
  providerData: { providerId: string }[];
  getIdToken: () => Promise<string>;
}

function _makeUser(overrides: Partial<MockUser> = {}): MockUser {
  return {
    uid: "u-1",
    email: "jane@example.com",
    displayName: "Jane",
    emailVerified: false,
    providerData: [{ providerId: "password" }],
    getIdToken: async () => "id-token-123",
    ...overrides,
  };
}

interface MockState {
  callback: IdTokenCallback | null;
  user: MockUser | null;
  signInPopupCalls: number;
  signInRedirectCalls: number;
  signOutCalls: number;
  signInEmailCalls: { email: string; password: string }[];
  signUpEmailCalls: { email: string; password: string }[];
  resetCalls: string[];
  verifyCalls: number;
  popupError: Error | null;
  emailError: Error | null;
  createError: Error | null;
  resetError: Error | null;
  verifyError: Error | null;
}

const _state: MockState = {
  callback: null,
  user: null,
  signInPopupCalls: 0,
  signInRedirectCalls: 0,
  signOutCalls: 0,
  signInEmailCalls: [],
  signUpEmailCalls: [],
  resetCalls: [],
  verifyCalls: 0,
  popupError: null,
  emailError: null,
  createError: null,
  resetError: null,
  verifyError: null,
};

vi.mock("firebase/app", () => ({
  initializeApp: vi.fn((cfg) => ({ options: cfg })),
  getApps: vi.fn(() => []),
}));

vi.mock("firebase/auth", () => ({
  getAuth: vi.fn(() => ({})),
  GoogleAuthProvider: vi.fn(() => ({})),
  onIdTokenChanged: vi.fn((_auth, cb: IdTokenCallback) => {
    _state.callback = cb;
    cb(_state.user);
    return () => {
      _state.callback = null;
    };
  }),
  getRedirectResult: vi.fn(async () => null),
  signInWithPopup: vi.fn(async () => {
    _state.signInPopupCalls++;
    if (_state.popupError) throw _state.popupError;
    const u = _makeUser({ providerData: [{ providerId: "google.com" }], emailVerified: true });
    _state.user = u;
    _state.callback?.(u);
    return { user: u };
  }),
  signInWithRedirect: vi.fn(async () => {
    _state.signInRedirectCalls++;
  }),
  signInWithEmailAndPassword: vi.fn(async (_auth, email: string, password: string) => {
    _state.signInEmailCalls.push({ email, password });
    if (_state.emailError) throw _state.emailError;
    const u = _makeUser({ email });
    _state.user = u;
    _state.callback?.(u);
    return { user: u };
  }),
  createUserWithEmailAndPassword: vi.fn(async (_auth, email: string, password: string) => {
    _state.signUpEmailCalls.push({ email, password });
    if (_state.createError) throw _state.createError;
    const u = _makeUser({ email, emailVerified: false });
    _state.user = u;
    _state.callback?.(u);
    return { user: u };
  }),
  sendPasswordResetEmail: vi.fn(async (_auth, email: string) => {
    _state.resetCalls.push(email);
    if (_state.resetError) throw _state.resetError;
  }),
  sendEmailVerification: vi.fn(async () => {
    _state.verifyCalls++;
    if (_state.verifyError) throw _state.verifyError;
  }),
  signOut: vi.fn(async () => {
    _state.signOutCalls++;
    _state.user = null;
    _state.callback?.(null);
  }),
}));

// ---------------------------------------------------------------------------
// Helpers to re-import the modules cleanly after stubbing env
// ---------------------------------------------------------------------------

async function loadModules() {
  vi.resetModules();
  const cfgModule = await import("../src/auth/firebaseConfig");
  const authModule = await import("../src/auth/useAuth");
  return { cfgModule, authModule };
}

beforeEach(() => {
  _state.callback = null;
  _state.user = null;
  _state.signInPopupCalls = 0;
  _state.signInRedirectCalls = 0;
  _state.signOutCalls = 0;
  _state.signInEmailCalls = [];
  _state.signUpEmailCalls = [];
  _state.resetCalls = [];
  _state.verifyCalls = 0;
  _state.popupError = null;
  _state.emailError = null;
  _state.createError = null;
  _state.resetError = null;
  _state.verifyError = null;
});

afterEach(() => {
  vi.unstubAllEnvs();
});

// ---------------------------------------------------------------------------
// Not configured (no env vars)
// ---------------------------------------------------------------------------

describe("firebaseConfig — not configured", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "");
  });

  it("isFirebaseConfigured is false", async () => {
    const { cfgModule } = await loadModules();
    expect(cfgModule.isFirebaseConfigured).toBe(false);
    expect(cfgModule.firebaseConfig).toBeNull();
  });

  it("getFirebaseApp returns null", async () => {
    const { cfgModule } = await loadModules();
    expect(cfgModule.getFirebaseApp()).toBeNull();
  });

  it("getFirebaseAuth returns null", async () => {
    const { cfgModule } = await loadModules();
    expect(cfgModule.getFirebaseAuth()).toBeNull();
  });
});

describe("useAuth — not configured", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "");
  });

  it("returns configured=false, user=null, loading=false immediately", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.configured).toBe(false);
    expect(result.current.user).toBeNull();
  });

  it("getIdToken returns null when no user", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const tok = await result.current.getIdToken();
    expect(tok).toBeNull();
  });

  it("signIn throws when Firebase is not configured", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(result.current.signIn()).rejects.toThrow(/Firebase is not configured/);
  });

  it("signInWithEmail throws when not configured", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(result.current.signInWithEmail("x@y.z", "pw")).rejects.toThrow(
      /Firebase is not configured/,
    );
  });

  it("signOut is a no-op when Firebase is not configured", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(result.current.signOut()).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Configured (env vars stubbed)
// ---------------------------------------------------------------------------

describe("firebaseConfig — configured", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "fake-api-key");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "demo.firebaseapp.com");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "demo-project");
  });

  it("isFirebaseConfigured is true when all three vars are set", async () => {
    const { cfgModule } = await loadModules();
    expect(cfgModule.isFirebaseConfigured).toBe(true);
    expect(cfgModule.firebaseConfig).toEqual(
      expect.objectContaining({
        apiKey: "fake-api-key",
        authDomain: "demo.firebaseapp.com",
        projectId: "demo-project",
      }),
    );
  });

  it("getFirebaseApp returns the same instance on repeat calls", async () => {
    const { cfgModule } = await loadModules();
    const a = cfgModule.getFirebaseApp();
    const b = cfgModule.getFirebaseApp();
    expect(a).not.toBeNull();
    expect(a).toBe(b);
  });
});

describe("useAuth — configured, Google popup", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "fake-api-key");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "demo.firebaseapp.com");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "demo-project");
  });

  it("starts with loading=true until onIdTokenChanged fires", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.configured).toBe(true);
    expect(result.current.user).toBeNull();
  });

  it("signIn populates user", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.signIn();
    });
    await waitFor(() => expect(result.current.user?.email).toBe("jane@example.com"));
  });

  it("signIn falls back to redirect when popup is blocked", async () => {
    _state.popupError = Object.assign(new Error("blocked"), {
      code: "auth/popup-blocked",
    });
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.signIn();
    });
    expect(_state.signInPopupCalls).toBe(1);
    expect(_state.signInRedirectCalls).toBe(1);
  });

  it("signIn rethrows a friendly error for non-popup failures", async () => {
    _state.popupError = Object.assign(new Error("boom"), {
      code: "auth/user-disabled",
    });
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(
      act(async () => {
        await result.current.signIn();
      }),
    ).rejects.toMatchObject({ code: "auth/user-disabled" });
    expect(_state.signInRedirectCalls).toBe(0);
  });

  it("getIdToken returns token from signed-in user", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.signIn();
    });
    const tok = await result.current.getIdToken();
    expect(tok).toBe("id-token-123");
  });

  it("signOut clears user", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.signIn();
    });
    await waitFor(() => expect(result.current.user).not.toBeNull());
    await act(async () => {
      await result.current.signOut();
    });
    await waitFor(() => expect(result.current.user).toBeNull());
  });
});

describe("useAuth — email/password flows", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "fake-api-key");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "demo.firebaseapp.com");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "demo-project");
  });

  it("signInWithEmail populates user and passes through credentials", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.signInWithEmail("kai@example.com", "hunter2");
    });
    expect(_state.signInEmailCalls).toEqual([{ email: "kai@example.com", password: "hunter2" }]);
    expect(result.current.user?.email).toBe("kai@example.com");
  });

  it("signInWithEmail converts Firebase errors to friendly ones", async () => {
    _state.emailError = Object.assign(new Error("no"), {
      code: "auth/wrong-password",
    });
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(
      act(async () => {
        await result.current.signInWithEmail("kai@example.com", "bad");
      }),
    ).rejects.toMatchObject({
      code: "auth/wrong-password",
      message: "Incorrect email or password.",
    });
  });

  it("signUpWithEmail creates user + auto-sends verification", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.signUpWithEmail("new@example.com", "hunter2");
    });
    expect(_state.signUpEmailCalls).toHaveLength(1);
    expect(_state.verifyCalls).toBe(1);
  });

  it("signUpWithEmail surfaces email-already-in-use as friendly error", async () => {
    _state.createError = Object.assign(new Error("no"), {
      code: "auth/email-already-in-use",
    });
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(
      act(async () => {
        await result.current.signUpWithEmail("dup@example.com", "hunter2");
      }),
    ).rejects.toMatchObject({ code: "auth/email-already-in-use" });
    expect(_state.verifyCalls).toBe(0);
  });

  it("signUpWithEmail swallows sendEmailVerification failures", async () => {
    _state.verifyError = new Error("smtp down");
    // Silence the warning but don't assert on it — the important
    // behaviour is that signUpWithEmail RESOLVES despite the SMTP
    // failure, and that verifyCalls still incremented (proving the
    // verification mock actually threw).
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(
      act(async () => {
        await result.current.signUpWithEmail("new@example.com", "hunter2");
      }),
    ).resolves.toBeUndefined();
    expect(_state.verifyCalls).toBe(1);
  });

  it("sendPasswordReset calls Firebase with the email", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.sendPasswordReset("kai@example.com");
    });
    expect(_state.resetCalls).toEqual(["kai@example.com"]);
  });

  it("sendPasswordReset surfaces invalid-email as friendly error", async () => {
    _state.resetError = Object.assign(new Error("no"), {
      code: "auth/invalid-email",
    });
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(
      act(async () => {
        await result.current.sendPasswordReset("bogus");
      }),
    ).rejects.toMatchObject({ code: "auth/invalid-email" });
  });

  it("resendVerification rejects when no user signed in", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(
      act(async () => {
        await result.current.resendVerification();
      }),
    ).rejects.toMatchObject({ code: "auth/not-signed-in" });
  });

  it("resendVerification rejects when user is already verified", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    // Sign in via Google (mock marks emailVerified=true).
    await act(async () => {
      await result.current.signIn();
    });
    await waitFor(() => expect(result.current.user?.emailVerified).toBe(true));
    await expect(
      act(async () => {
        await result.current.resendVerification();
      }),
    ).rejects.toMatchObject({ code: "auth/already-verified" });
  });

  it("resendVerification calls Firebase when user is unverified", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    // Email sign-up creates an unverified user.
    await act(async () => {
      await result.current.signUpWithEmail("new@example.com", "hunter2");
    });
    expect(_state.verifyCalls).toBe(1); // auto-send
    await act(async () => {
      await result.current.resendVerification();
    });
    expect(_state.verifyCalls).toBe(2); // manual resend
  });
});
