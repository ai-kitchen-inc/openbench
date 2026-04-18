/**
 * Tests for the Firebase → user-friendly error mapper.
 *
 * Kept after removing email/password flows: the Google popup flow still
 * returns popup-blocked, popup-closed-by-user, unauthorized-domain, and
 * network-request-failed in practice, and the mapper is what stops them
 * from bubbling up as raw Firebase messages.
 */

import { describe, expect, it } from "vitest";

import { isPopupBlocked, toFriendlyAuthError } from "../src/auth/authErrors";


function firebaseError(code: string, message = "raw firebase msg") {
  const err = new Error(message) as Error & { code: string };
  err.code = code;
  return err;
}


describe("toFriendlyAuthError", () => {
  it("maps popup-blocked to a redirect-fallback message", () => {
    const e = toFriendlyAuthError(firebaseError("auth/popup-blocked"));
    expect(e.message).toMatch(/popup was blocked/i);
    expect(e.code).toBe("auth/popup-blocked");
  });

  it("maps popup-closed-by-user to a retry message", () => {
    const e = toFriendlyAuthError(firebaseError("auth/popup-closed-by-user"));
    expect(e.message).toMatch(/closed before finishing/i);
  });

  it("maps unauthorized-domain to a contact-support message", () => {
    const e = toFriendlyAuthError(firebaseError("auth/unauthorized-domain"));
    expect(e.message).toMatch(/isn't authorised/i);
  });

  it("maps network-request-failed to a retry message", () => {
    const e = toFriendlyAuthError(firebaseError("auth/network-request-failed"));
    expect(e.message).toMatch(/network error/i);
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
    expect(isPopupBlocked("auth/unknown")).toBe(false);
  });
});
