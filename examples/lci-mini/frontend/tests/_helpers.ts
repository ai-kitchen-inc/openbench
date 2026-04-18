/**
 * Test helpers shared across the auth test suite.
 *
 * ``fakeAuth`` returns a fully-typed :type:`UseAuthReturn` with every
 * method pre-stubbed. When :type:`UseAuthReturn` gains or loses a
 * field, update this one file.
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
    signOut: vi.fn().mockResolvedValue(undefined),
    getIdToken: vi.fn().mockResolvedValue(hasUser ? "fake-id-token" : null),
    ...overrides,
  };
}


interface FakeUserOpts {
  uid?: string;
  email?: string | null;
  displayName?: string | null;
  photoURL?: string | null;
}

export function fakeUser(opts: FakeUserOpts = {}) {
  return {
    uid: opts.uid ?? "u-1",
    email: opts.email === undefined ? "jane@example.com" : opts.email,
    displayName: opts.displayName === undefined ? "Jane" : opts.displayName,
    photoURL: opts.photoURL === undefined ? null : opts.photoURL,
    getIdToken: async () => "fake-id-token",
  } as never;
}
