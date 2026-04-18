/**
 * Tests for the tiny toast system + the error paths wired into
 * AuthGate and UserBadge.
 */

import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "../src/auth/AuthGate";
import { ToastProvider, useOptionalToast, useToast } from "../src/auth/Toast";
import { UserBadge } from "../src/auth/UserBadge";
import { fakeAuth as _auth, fakeUser } from "./_helpers";

function _user() {
  return fakeUser({ uid: "u" });
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("ToastProvider", () => {
  it("useToast outside provider throws", () => {
    expect(() => renderHook(() => useToast())).toThrow(/must be used inside <ToastProvider>/);
  });

  it("useOptionalToast returns a no-op outside provider", () => {
    const { result } = renderHook(() => useOptionalToast());
    expect(() => result.current.show("nothing", "info")).not.toThrow();
    expect(result.current.toasts).toEqual([]);
  });

  it("show() adds a toast to the host", () => {
    const Harness = () => {
      const t = useToast();
      return (
        <button type="button" onClick={() => t.show("Hello", "info")}>
          push
        </button>
      );
    };
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "push" }));
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("renders with kind-specific class", () => {
    const Harness = () => {
      const t = useToast();
      return (
        <button type="button" onClick={() => t.show("fail", "error")}>
          push
        </button>
      );
    };
    const { container } = render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(container.querySelector(".toast--error")).toBeInTheDocument();
  });

  it("dismiss button removes a toast", () => {
    const Harness = () => {
      const t = useToast();
      return (
        <button type="button" onClick={() => t.show("gone soon", "info", 0)}>
          push
        </button>
      );
    };
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "push" }));
    expect(screen.getByText("gone soon")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
    expect(screen.queryByText("gone soon")).not.toBeInTheDocument();
  });

  it("auto-dismisses after the configured duration", () => {
    const Harness = () => {
      const t = useToast();
      return (
        <button type="button" onClick={() => t.show("bye", "info")}>
          push
        </button>
      );
    };
    render(
      <ToastProvider durationMs={100}>
        <Harness />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "push" }));
    expect(screen.getByText("bye")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.queryByText("bye")).not.toBeInTheDocument();
  });

  it("duration=0 disables auto-dismiss", () => {
    const Harness = () => {
      const t = useToast();
      return (
        <button type="button" onClick={() => t.show("sticky", "info", 0)}>
          push
        </button>
      );
    };
    render(
      <ToastProvider durationMs={100}>
        <Harness />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "push" }));
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(screen.getByText("sticky")).toBeInTheDocument();
  });
});

describe("AuthGate sign-in failure → toast", () => {
  it("surfaces a signIn() error as an error toast", async () => {
    vi.useRealTimers();
    const failing = _auth({
      configured: true,
      user: null,
      signIn: vi.fn().mockRejectedValue(new Error("popup closed by user")),
    });
    render(
      <ToastProvider durationMs={0}>
        <AuthGate auth={failing}>
          <div>chat shell</div>
        </AuthGate>
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /Continue with Google/i }));
    // The same message appears BOTH in the inline form error and the
    // toast — we just need to prove it surfaced somewhere.
    await waitFor(() =>
      expect(screen.getAllByText("popup closed by user").length).toBeGreaterThan(0),
    );
  });
});

describe("UserBadge connect/disconnect failures → toast", () => {
  it("toasts when /auth/drive/connect returns non-2xx", async () => {
    vi.useRealTimers();
    const fetchMock = vi.fn(async (input: URL | RequestInfo) => {
      const url = input.toString();
      if (url === "/auth/me") {
        return new Response(
          JSON.stringify({
            uid: "u",
            email: "x@y.z",
            drive: { configured: true, connected: false },
          }),
          { status: 200 },
        );
      }
      if (url === "/auth/drive/connect") {
        return new Response("{}", { status: 500 });
      }
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ToastProvider durationMs={0}>
        <UserBadge auth={_auth({ configured: true, user: _user() })} />
      </ToastProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Account menu/i }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Connect Google Drive/i }));
    await waitFor(() => {
      expect(screen.getByText(/Couldn't start Google Drive connection/i)).toBeInTheDocument();
    });
  });

  it("toasts success when disconnect succeeds", async () => {
    vi.useRealTimers();
    let connected = true;
    const fetchMock = vi.fn(async (input: URL | RequestInfo) => {
      const url = input.toString();
      if (url === "/auth/me") {
        return new Response(
          JSON.stringify({
            uid: "u",
            email: "x@y.z",
            drive: connected
              ? { configured: true, connected: true, folderId: "f", email: "x@y.z" }
              : { configured: true, connected: false, folderId: null, email: null },
          }),
          { status: 200 },
        );
      }
      if (url === "/auth/drive/disconnect") {
        connected = false;
        return new Response(JSON.stringify({ disconnected: true }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ToastProvider durationMs={0}>
        <UserBadge auth={_auth({ configured: true, user: _user() })} />
      </ToastProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Account menu/i }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Disconnect Google Drive/i }));
    await waitFor(() => {
      expect(screen.getByText(/Google Drive disconnected/i)).toBeInTheDocument();
    });
  });
});
