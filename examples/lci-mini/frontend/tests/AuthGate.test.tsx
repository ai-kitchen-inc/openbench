/**
 * Tests for AuthGate — Google-only sign-in screen.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuthGate } from "../src/auth/AuthGate";
import { ToastProvider } from "../src/auth/Toast";
import { fakeAuth, fakeUser } from "./_helpers";


function renderGate(
  auth: ReturnType<typeof fakeAuth>,
  opts: { requireConfigured?: boolean } = {},
) {
  return render(
    <ToastProvider durationMs={0}>
      <AuthGate auth={auth} requireConfigured={opts.requireConfigured}>
        <div>chat shell</div>
      </AuthGate>
    </ToastProvider>,
  );
}


describe("AuthGate — gating", () => {
  it("shows not-configured screen when Firebase is not configured (default)", () => {
    renderGate(fakeAuth({ configured: false }));
    expect(
      screen.getByRole("heading", { name: /Sign-in not configured/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });

  it("opt-out passthrough when requireConfigured=false", () => {
    renderGate(fakeAuth({ configured: false }), { requireConfigured: false });
    expect(screen.getByText("chat shell")).toBeInTheDocument();
  });

  it("renders loading spinner when configured + loading=true", () => {
    renderGate(fakeAuth({ configured: true, loading: true }));
    expect(screen.getByText(/Checking sign-in/i)).toBeInTheDocument();
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });

  it("renders the Google sign-in screen when configured + signed-out", () => {
    renderGate(fakeAuth({ configured: true, user: null }));
    expect(
      screen.getByRole("button", { name: /Continue with Google/i }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });

  it("passes through when configured + signed-in", () => {
    renderGate(fakeAuth({ configured: true, user: fakeUser() }));
    expect(screen.getByText("chat shell")).toBeInTheDocument();
  });
});


describe("AuthGate — Google sign-in", () => {
  it("button invokes auth.signIn", async () => {
    const auth = fakeAuth({ configured: true, user: null });
    renderGate(auth);
    await userEvent.click(
      screen.getByRole("button", { name: /Continue with Google/i }),
    );
    expect(auth.signIn).toHaveBeenCalledTimes(1);
  });

  it("surfaces a friendly error when sign-in fails", async () => {
    const auth = fakeAuth({
      configured: true,
      user: null,
      signIn: vi.fn().mockRejectedValue(
        Object.assign(new Error("raw"), {
          code: "auth/popup-closed-by-user",
        }),
      ),
    });
    renderGate(auth);
    await userEvent.click(
      screen.getByRole("button", { name: /Continue with Google/i }),
    );
    await waitFor(() =>
      expect(
        screen.getAllByText(/closed before finishing/i).length,
      ).toBeGreaterThan(0),
    );
  });

  it("disables the button while busy", async () => {
    let resolve!: () => void;
    const pending = new Promise<void>((r) => {
      resolve = r;
    });
    const auth = fakeAuth({
      configured: true,
      user: null,
      signIn: vi.fn().mockReturnValue(pending),
    });
    renderGate(auth);
    const btn = screen.getByRole("button", { name: /Continue with Google/i });
    await userEvent.click(btn);
    // While the promise hasn't resolved, button stays disabled.
    await waitFor(() => expect(btn).toBeDisabled());
    resolve();
  });
});
