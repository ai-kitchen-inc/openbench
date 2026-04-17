/**
 * Tests for AuthGate — the pre-chat sign-in screen.
 *
 * Three states matter:
 * 1. Firebase not configured → passthrough (renders children).
 * 2. Configured + loading   → shows the spinner.
 * 3. Configured + signed-out → shows "Sign in with Google".
 * 4. Configured + signed-in  → passthrough.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthGate } from "../src/auth/AuthGate";
import type { UseAuthReturn } from "../src/auth/useAuth";

function _auth(overrides: Partial<UseAuthReturn> = {}): UseAuthReturn {
  return {
    user: null,
    loading: false,
    configured: false,
    signIn: vi.fn().mockResolvedValue(undefined),
    signOut: vi.fn().mockResolvedValue(undefined),
    getIdToken: vi.fn().mockResolvedValue(null),
    ...overrides,
  };
}

describe("AuthGate", () => {
  it("passes through when Firebase is not configured", () => {
    render(
      <AuthGate auth={_auth({ configured: false })}>
        <div>chat shell</div>
      </AuthGate>,
    );
    expect(screen.getByText("chat shell")).toBeInTheDocument();
  });

  it("renders loading spinner when configured + loading=true", () => {
    render(
      <AuthGate auth={_auth({ configured: true, loading: true })}>
        <div>chat shell</div>
      </AuthGate>,
    );
    expect(screen.getByText(/Checking sign-in/i)).toBeInTheDocument();
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });

  it("renders the sign-in screen when configured + signed-out", () => {
    render(
      <AuthGate auth={_auth({ configured: true, loading: false, user: null })}>
        <div>chat shell</div>
      </AuthGate>,
    );
    expect(screen.getByText(/Sign in with Google/i)).toBeInTheDocument();
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });

  it("passes through when configured + signed-in", () => {
    const user = {
      uid: "u",
      email: "u@x.y",
      displayName: "U",
      getIdToken: async () => "tok",
    } as never;
    render(
      <AuthGate auth={_auth({ configured: true, loading: false, user })}>
        <div>chat shell</div>
      </AuthGate>,
    );
    expect(screen.getByText("chat shell")).toBeInTheDocument();
  });

  it("sign-in button triggers auth.signIn", () => {
    const auth = _auth({ configured: true, loading: false, user: null });
    render(
      <AuthGate auth={auth}>
        <div>chat shell</div>
      </AuthGate>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Sign in with Google/i }));
    expect(auth.signIn).toHaveBeenCalledTimes(1);
  });

  it("sign-in button errors are caught so they don't bubble up", async () => {
    const failing = _auth({
      configured: true,
      loading: false,
      user: null,
      signIn: vi.fn().mockRejectedValue(new Error("popup closed")),
    });
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <AuthGate auth={failing}>
        <div>chat shell</div>
      </AuthGate>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Sign in with Google/i }));
    // Allow microtask to settle
    await new Promise((r) => setTimeout(r, 0));
    // Error was logged, not thrown
    expect(errSpy).toHaveBeenCalled();
    errSpy.mockRestore();
  });
});
