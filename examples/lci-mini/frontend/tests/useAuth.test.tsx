/**
 * Tests for useAuth + firebaseConfig (Google-only auth).
 *
 * Two modes:
 *   - "not configured" — env vars unset.
 *   - "configured"     — env vars stubbed via vi.stubEnv; firebase/auth
 *                        mocked so no real SDK init happens.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";


// ---------------------------------------------------------------------------
// Firebase mocks
// ---------------------------------------------------------------------------


type IdTokenCallback = (u: MockUser | null) => void;

interface MockUser {
  uid: string;
  email: string | null;
  displayName: string | null;
  getIdToken: () => Promise<string>;
}

interface MockState {
  callback: IdTokenCallback | null;
  user: MockUser | null;
  popupCalls: number;
  redirectCalls: number;
  signOutCalls: number;
  popupError: Error | null;
}

const _state: MockState = {
  callback: null,
  user: null,
  popupCalls: 0,
  redirectCalls: 0,
  signOutCalls: 0,
  popupError: null,
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
    _state.popupCalls++;
    if (_state.popupError) throw _state.popupError;
    const u: MockUser = {
      uid: "u-1",
      email: "jane@example.com",
      displayName: "Jane",
      getIdToken: async () => "id-token-123",
    };
    _state.user = u;
    _state.callback?.(u);
    return { user: u };
  }),
  signInWithRedirect: vi.fn(async () => {
    _state.redirectCalls++;
  }),
  signOut: vi.fn(async () => {
    _state.signOutCalls++;
    _state.user = null;
    _state.callback?.(null);
  }),
}));


async function loadModules() {
  vi.resetModules();
  const cfgModule = await import("../src/auth/firebaseConfig");
  const authModule = await import("../src/auth/useAuth");
  return { cfgModule, authModule };
}


beforeEach(() => {
  _state.callback = null;
  _state.user = null;
  _state.popupCalls = 0;
  _state.redirectCalls = 0;
  _state.signOutCalls = 0;
  _state.popupError = null;
});

afterEach(() => {
  vi.unstubAllEnvs();
});


// ---------------------------------------------------------------------------
// Not configured
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

  it("returns configured=false, user=null, loading=false", async () => {
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
    expect(await result.current.getIdToken()).toBeNull();
  });

  it("signIn throws when not configured", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(result.current.signIn()).rejects.toThrow(/not configured/i);
  });

  it("signOut is a no-op when not configured", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(result.current.signOut()).resolves.toBeUndefined();
  });
});


// ---------------------------------------------------------------------------
// Configured
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
  });

  it("getFirebaseApp returns the same instance on repeat calls", async () => {
    const { cfgModule } = await loadModules();
    const a = cfgModule.getFirebaseApp();
    const b = cfgModule.getFirebaseApp();
    expect(a).not.toBeNull();
    expect(a).toBe(b);
  });
});


describe("useAuth — configured (Google popup)", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "fake-api-key");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "demo.firebaseapp.com");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "demo-project");
  });

  it("loading flips off after onIdTokenChanged fires", async () => {
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
    expect(_state.popupCalls).toBe(1);
    expect(_state.redirectCalls).toBe(1);
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
    expect(_state.redirectCalls).toBe(0);
  });

  it("getIdToken returns token from signed-in user", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.signIn();
    });
    expect(await result.current.getIdToken()).toBe("id-token-123");
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
