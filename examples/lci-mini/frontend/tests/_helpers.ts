/**
 * Test helpers shared across the auth test suite.
 *
 * ``fakeAuth`` returns a fully-typed :type:`UseAuthReturn` with every
 * method pre-stubbed, so individual tests only need to override the
 * fields they exercise. Keeping this in one place means adding new
 * methods to ``UseAuthReturn`` requires exactly one update.
 */

import { vi } from "vitest";
import type { UseAuthReturn } from "../src/auth/useAuth";

export function fakeAuth(overrides: Partial<UseAuthReturn> = {}): UseAuthReturn {
  const hasUser = !!overrides.user;
  return {
    user: null,
    loading: false,
    configured: false,
    signIn: vi.fn().mockResolvedValue(undefined),
    signInWithEmail: vi.fn().mockResolvedValue(undefined),
    signUpWithEmail: vi.fn().mockResolvedValue(undefined),
    sendPasswordReset: vi.fn().mockResolvedValue(undefined),
    resendVerification: vi.fn().mockResolvedValue(undefined),
    signOut: vi.fn().mockResolvedValue(undefined),
    getIdToken: vi.fn().mockResolvedValue(hasUser ? "fake-id-token" : null),
    ...overrides,
  };
}

interface FakeUserOpts {
  uid?: string;
  email?: string | null;
  displayName?: string | null;
  emailVerified?: boolean;
  providerId?: "password" | "google.com";
}

export function fakeUser(opts: FakeUserOpts = {}) {
  const providerId = opts.providerId ?? "password";
  return {
    uid: opts.uid ?? "u-1",
    email: opts.email === undefined ? "jane@example.com" : opts.email,
    displayName: opts.displayName === undefined ? "Jane" : opts.displayName,
    emailVerified: opts.emailVerified ?? false,
    providerData: [{ providerId }],
    getIdToken: async () => "fake-id-token",
  } as never;
}
