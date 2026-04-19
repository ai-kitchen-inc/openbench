/**
 * Tests for AuthGate — Google-only sign-in screen.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "../src/auth/AuthGate";
import { ToastProvider } from "../src/auth/Toast";
import { fakeAuth, fakeUser } from "./_helpers";


/**
 * Install a ``fetch`` stub that answers ``/auth/me`` with the given
 * status + body. AuthGate's new approval gate hits this endpoint on
 * every signed-in render, so without a stub the tests either log
 * "fetch failed" warnings or hang waiting for the real network.
 */
function mockAuthMe(
  status: number,
  body: Record<string, unknown> = { uid: "u" },
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (input: URL | RequestInfo) => {
    const url = input.toString();
    if (url === "/auth/me") {
      return new Response(JSON.stringify(body), { status });
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  mockAuthMe(200);
});

afterEach(() => {
  vi.unstubAllGlobals();
});


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

  it("passes through when configured + signed-in + approved", async () => {
    mockAuthMe(200);
    renderGate(fakeAuth({ configured: true, user: fakeUser() }));
    // First paint shows the "Checking sign-in" spinner while the
    // approval check is in flight; chat shell appears once /auth/me
    // resolves 200.
    await waitFor(() =>
      expect(screen.getByText("chat shell")).toBeInTheDocument(),
    );
  });

  it("renders pending-approval screen on 403 pending_approval", async () => {
    mockAuthMe(403, { detail: "pending_approval" });
    renderGate(fakeAuth({ configured: true, user: fakeUser() }));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Waiting for approval/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });

  it("renders account-disabled screen on 401 account_disabled", async () => {
    mockAuthMe(401, { detail: "account_disabled" });
    renderGate(fakeAuth({ configured: true, user: fakeUser() }));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Account disabled/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("chat shell")).not.toBeInTheDocument();
  });

  it("lets the user in on transient /auth/me 500", async () => {
    // An unrecognised error must NOT lock legit users out; the real
    // chat request will surface the issue instead.
    mockAuthMe(500, { detail: "internal_error" });
    renderGate(fakeAuth({ configured: true, user: fakeUser() }));
    await waitFor(() =>
      expect(screen.getByText("chat shell")).toBeInTheDocument(),
    );
  });

  it("pending-approval screen sign-out button calls auth.signOut", async () => {
    mockAuthMe(403, { detail: "pending_approval" });
    const auth = fakeAuth({ configured: true, user: fakeUser() });
    renderGate(auth);
    await screen.findByRole("heading", { name: /Waiting for approval/i });
    await userEvent.click(screen.getByRole("button", { name: /Sign out/i }));
    expect(auth.signOut).toHaveBeenCalledTimes(1);
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
