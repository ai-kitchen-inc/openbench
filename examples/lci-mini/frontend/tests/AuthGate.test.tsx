/**
 * Tests for AuthGate — the pre-chat sign-in screen.
 *
 * Exercises all three view modes (signin, register, forgot), both
 * success and error paths for each, the verification banner, and the
 * "requireEmailVerified" hard gate.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuthGate } from "../src/auth/AuthGate";
import { ToastProvider } from "../src/auth/Toast";
import { fakeAuth, fakeUser } from "./_helpers";

function renderGate(
  auth: ReturnType<typeof fakeAuth>,
  opts: { requireEmailVerified?: boolean } = {},
) {
  return render(
    <ToastProvider durationMs={0}>
      <AuthGate auth={auth} requireEmailVerified={opts.requireEmailVerified}>
        <div>chat shell</div>
      </AuthGate>
    </ToastProvider>,
  );
}

describe("AuthGate — gating", () => {
  it("passes through when Firebase is not configured", () => {
    renderGate(fakeAuth({ configured: false }));
    expect(screen.getByText("chat shell")).toBeInTheDocument();
  });

  it("renders loading spinner when configured + loading=true", () => {
    renderGate(fakeAuth({ configured: true, loading: true }));
    expect(screen.getByText(/Checking sign-in/i)).toBeInTheDocument();
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });

  it("renders the sign-in screen when configured + signed-out", () => {
    renderGate(fakeAuth({ configured: true, loading: false, user: null }));
    expect(screen.getByRole("button", { name: /^Sign in$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sign in with Google/i })).toBeInTheDocument();
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });

  it("passes through when configured + signed-in + verified", () => {
    renderGate(
      fakeAuth({
        configured: true,
        loading: false,
        user: fakeUser({ emailVerified: true }),
      }),
    );
    expect(screen.getByText("chat shell")).toBeInTheDocument();
  });

  it("shows verify banner when email/password user is unverified", () => {
    renderGate(
      fakeAuth({
        configured: true,
        user: fakeUser({ emailVerified: false, providerId: "password" }),
      }),
    );
    expect(screen.getByText("chat shell")).toBeInTheDocument();
    expect(screen.getByText(/verify your email/i)).toBeInTheDocument();
  });

  it("does NOT show verify banner for Google-signed-in users", () => {
    renderGate(
      fakeAuth({
        configured: true,
        user: fakeUser({ emailVerified: false, providerId: "google.com" }),
      }),
    );
    expect(screen.getByText("chat shell")).toBeInTheDocument();
    expect(screen.queryByText(/verify your email/i)).not.toBeInTheDocument();
  });

  it("blocks app when requireEmailVerified=true + unverified", () => {
    renderGate(
      fakeAuth({
        configured: true,
        user: fakeUser({ emailVerified: false, providerId: "password" }),
      }),
      { requireEmailVerified: true },
    );
    expect(screen.getByRole("heading", { name: /Verify your email/i })).toBeInTheDocument();
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });
});

describe("AuthGate — email/password sign in", () => {
  it("submits email + password to auth.signInWithEmail", async () => {
    const auth = fakeAuth({ configured: true, user: null });
    renderGate(auth);

    await userEvent.type(screen.getByLabelText("Email"), "jane@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "hunter2");
    await userEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

    expect(auth.signInWithEmail).toHaveBeenCalledWith("jane@example.com", "hunter2");
  });

  it("displays a friendly error when sign-in fails", async () => {
    const auth = fakeAuth({
      configured: true,
      user: null,
      signInWithEmail: vi.fn().mockRejectedValue(
        Object.assign(new Error("FIREBASE_INTERNAL"), {
          code: "auth/wrong-password",
        }),
      ),
    });
    renderGate(auth);

    await userEvent.type(screen.getByLabelText("Email"), "jane@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

    await waitFor(() =>
      expect(screen.getAllByText(/incorrect email or password/i).length).toBeGreaterThan(0),
    );
  });

  it("switches to Google sign-in flow when button clicked", async () => {
    const auth = fakeAuth({ configured: true, user: null });
    renderGate(auth);
    await userEvent.click(screen.getByRole("button", { name: /Sign in with Google/i }));
    expect(auth.signIn).toHaveBeenCalledTimes(1);
  });
});

describe("AuthGate — registration", () => {
  it("switches to register view and submits", async () => {
    const auth = fakeAuth({ configured: true, user: null });
    renderGate(auth);

    await userEvent.click(screen.getByRole("button", { name: /Create account/i }));
    await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "hunter2");
    await userEvent.type(screen.getByLabelText("Confirm password"), "hunter2");
    await userEvent.click(screen.getByRole("button", { name: /^Create account$/i }));

    expect(auth.signUpWithEmail).toHaveBeenCalledWith("new@example.com", "hunter2");
  });

  it("blocks submission when passwords don't match (no API call)", async () => {
    const auth = fakeAuth({ configured: true, user: null });
    renderGate(auth);

    await userEvent.click(screen.getByRole("button", { name: /Create account/i }));
    await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "hunter2");
    await userEvent.type(screen.getByLabelText("Confirm password"), "different");
    await userEvent.click(screen.getByRole("button", { name: /^Create account$/i }));

    expect(auth.signUpWithEmail).not.toHaveBeenCalled();
    expect(screen.getByText(/Passwords don't match/i)).toBeInTheDocument();
  });

  it("blocks submission when password is too short", async () => {
    const auth = fakeAuth({ configured: true, user: null });
    renderGate(auth);

    await userEvent.click(screen.getByRole("button", { name: /Create account/i }));
    await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
    // Pad to pass HTML5 minLength but still trip our own 6-char guard? 5 fails both.
    // Use a value that's 5 chars long so client-side check fires cleanly.
    const shortInput = screen.getByLabelText("Password");
    const confirmInput = screen.getByLabelText("Confirm password");
    shortInput.removeAttribute("minLength");
    confirmInput.removeAttribute("minLength");
    await userEvent.type(shortInput, "12345");
    await userEvent.type(confirmInput, "12345");
    await userEvent.click(screen.getByRole("button", { name: /^Create account$/i }));

    expect(auth.signUpWithEmail).not.toHaveBeenCalled();
    expect(screen.getByText(/at least 6 characters/i)).toBeInTheDocument();
  });

  it("returns to sign-in view from register", async () => {
    const auth = fakeAuth({ configured: true, user: null });
    renderGate(auth);
    await userEvent.click(screen.getByRole("button", { name: /Create account/i }));
    await userEvent.click(screen.getByRole("button", { name: /Already have an account/i }));
    expect(screen.getByRole("button", { name: /^Sign in$/i })).toBeInTheDocument();
  });
});

describe("AuthGate — forgot password", () => {
  it("switches to forgot view and sends reset", async () => {
    const auth = fakeAuth({ configured: true, user: null });
    renderGate(auth);

    await userEvent.click(screen.getByRole("button", { name: /Forgot password/i }));
    await userEvent.type(screen.getByLabelText("Email"), "jane@example.com");
    await userEvent.click(screen.getByRole("button", { name: /Send reset link/i }));

    expect(auth.sendPasswordReset).toHaveBeenCalledWith("jane@example.com");
    // Confirmation text renders inline; multiple role="status" nodes
    // exist on the page (toast host + inline info), so assert on the
    // text itself rather than the role.
    await waitFor(() => expect(screen.getAllByText(/Reset email sent/i).length).toBeGreaterThan(0));
  });

  it("shows friendly error when reset fails", async () => {
    const auth = fakeAuth({
      configured: true,
      user: null,
      sendPasswordReset: vi
        .fn()
        .mockRejectedValue(Object.assign(new Error("boom"), { code: "auth/invalid-email" })),
    });
    renderGate(auth);

    await userEvent.click(screen.getByRole("button", { name: /Forgot password/i }));
    // HTML5 form validation rejects non-email strings before the submit
    // handler runs, so use a syntactically-valid email and let the mock
    // throw auth/invalid-email to exercise the error path.
    await userEvent.type(screen.getByLabelText("Email"), "pre-test@example.com");
    await userEvent.click(screen.getByRole("button", { name: /Send reset link/i }));

    await waitFor(() =>
      expect(screen.getAllByText(/valid email address/i).length).toBeGreaterThan(0),
    );
  });
});

describe("AuthGate — verify email", () => {
  it("banner resend button triggers resendVerification", async () => {
    const auth = fakeAuth({
      configured: true,
      user: fakeUser({ emailVerified: false, providerId: "password" }),
    });
    renderGate(auth);

    await userEvent.click(screen.getByRole("button", { name: /^Resend$/i }));
    expect(auth.resendVerification).toHaveBeenCalledTimes(1);
  });

  it("hard-gate screen resend button triggers resendVerification", async () => {
    const auth = fakeAuth({
      configured: true,
      user: fakeUser({ emailVerified: false, providerId: "password" }),
    });
    renderGate(auth, { requireEmailVerified: true });

    await userEvent.click(screen.getByRole("button", { name: /Resend verification email/i }));
    expect(auth.resendVerification).toHaveBeenCalledTimes(1);
  });

  it("hard-gate 'sign out' button triggers signOut", async () => {
    const auth = fakeAuth({
      configured: true,
      user: fakeUser({ emailVerified: false, providerId: "password" }),
    });
    renderGate(auth, { requireEmailVerified: true });

    await userEvent.click(screen.getByRole("button", { name: /Sign out/i }));
    expect(auth.signOut).toHaveBeenCalledTimes(1);
  });
});
