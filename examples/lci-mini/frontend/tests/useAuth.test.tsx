/**
 * Tests for useAuth + firebaseConfig.
 *
 * Two modes are exercised:
 * - "not configured" — env vars unset. Default for the outer `describe`.
 * - "configured"     — env vars stubbed via `vi.stubEnv`; Firebase
 *    modules are mocked so no real SDK init happens.
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
  getIdToken: () => Promise<string>;
}

const _state: {
  callback: IdTokenCallback | null;
  user: MockUser | null;
  signInCalls: number;
  signOutCalls: number;
} = { callback: null, user: null, signInCalls: 0, signOutCalls: 0 };

vi.mock("firebase/app", () => ({
  initializeApp: vi.fn((cfg) => ({ options: cfg })),
  getApps: vi.fn(() => []),
}));

vi.mock("firebase/auth", () => ({
  getAuth: vi.fn(() => ({})),
  GoogleAuthProvider: vi.fn(() => ({})),
  onIdTokenChanged: vi.fn((_auth, cb: IdTokenCallback) => {
    _state.callback = cb;
    // Fire initial state immediately.
    cb(_state.user);
    return () => {
      _state.callback = null;
    };
  }),
  signInWithPopup: vi.fn(async () => {
    _state.signInCalls++;
    const fake: MockUser = {
      uid: "u-1",
      email: "jane@example.com",
      displayName: "Jane",
      getIdToken: async () => "id-token-123",
    };
    _state.user = fake;
    _state.callback?.(fake);
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
  _state.signInCalls = 0;
  _state.signOutCalls = 0;
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
    await expect(result.current.signIn()).rejects.toThrow(
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


describe("useAuth — configured", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "fake-api-key");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "demo.firebaseapp.com");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "demo-project");
  });

  it("starts with loading=true until onIdTokenChanged fires", async () => {
    const { authModule } = await loadModules();
    const { result } = renderHook(() => authModule.useAuth());
    // After the initial fire (synchronous in our mock), loading flips off.
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
