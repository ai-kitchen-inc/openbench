/**
 * Tests for the Firebase → user-friendly error mapper.
 */

import { describe, expect, it } from "vitest";

import { isPopupBlocked, toFriendlyAuthError } from "../src/auth/authErrors";

function firebaseError(code: string, message = "raw firebase msg") {
  const err = new Error(message) as Error & { code: string };
  err.code = code;
  return err;
}

describe("toFriendlyAuthError", () => {
  it("merges wrong-password and user-not-found into a single message", () => {
    const a = toFriendlyAuthError(firebaseError("auth/wrong-password"));
    const b = toFriendlyAuthError(firebaseError("auth/user-not-found"));
    const c = toFriendlyAuthError(firebaseError("auth/invalid-credential"));
    expect(a.message).toBe("Incorrect email or password.");
    expect(b.message).toBe(a.message);
    expect(c.message).toBe(a.message);
    // Code is preserved so UI can still branch if needed.
    expect(a.code).toBe("auth/wrong-password");
    expect(b.code).toBe("auth/user-not-found");
  });

  it("gives a shape-specific message for invalid-email", () => {
    const e = toFriendlyAuthError(firebaseError("auth/invalid-email"));
    expect(e.message).toMatch(/valid email address/i);
  });

  it("gives a registration-specific message for email-already-in-use", () => {
    const e = toFriendlyAuthError(firebaseError("auth/email-already-in-use"));
    expect(e.message).toMatch(/account already exists/i);
  });

  it("gives a specific message for weak-password", () => {
    const e = toFriendlyAuthError(firebaseError("auth/weak-password"));
    expect(e.message).toMatch(/too weak/i);
  });

  it("gives a rate-limit message for too-many-requests", () => {
    const e = toFriendlyAuthError(firebaseError("auth/too-many-requests"));
    expect(e.message).toMatch(/too many attempts/i);
  });

  it("falls back to the raw message when code is unknown", () => {
    const e = toFriendlyAuthError(firebaseError("auth/some-new-code", "raw 42"));
    expect(e.message).toBe("raw 42");
    expect(e.code).toBe("auth/some-new-code");
  });

  it("handles non-FirebaseError Error instances", () => {
    const e = toFriendlyAuthError(new Error("no code here"));
    expect(e.message).toBe("no code here");
    expect(e.code).toBe("auth/unknown");
  });

  it("handles non-Error values gracefully", () => {
    const e = toFriendlyAuthError("something weird");
    expect(e.message).toMatch(/Authentication failed/i);
    expect(e.code).toBe("auth/unknown");
  });
});

describe("isPopupBlocked", () => {
  it("returns true for auth/popup-blocked", () => {
    expect(isPopupBlocked("auth/popup-blocked")).toBe(true);
  });

  it("returns true for auth/operation-not-supported-in-this-environment", () => {
    expect(isPopupBlocked("auth/operation-not-supported-in-this-environment")).toBe(true);
  });

  it("returns false for other codes", () => {
    expect(isPopupBlocked("auth/popup-closed-by-user")).toBe(false);
    expect(isPopupBlocked("auth/wrong-password")).toBe(false);
    expect(isPopupBlocked("auth/unknown")).toBe(false);
  });
});
