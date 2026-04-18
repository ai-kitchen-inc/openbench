/**
 * Tests for UserBadge — header dropdown showing user + Drive status.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UserBadge } from "../src/auth/UserBadge";
import { fakeAuth as _auth, fakeUser } from "./_helpers";

function _user(email: string | null = "jane@example.com") {
  return fakeUser({ email });
}

function _installFetchMock(
  authMe: unknown,
  extras: Record<string, { status?: number; body?: unknown }> = {},
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (input: URL | RequestInfo, _init?: RequestInit) => {
    const url = input.toString();
    if (url === "/auth/me") {
      return new Response(JSON.stringify(authMe), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    const match = extras[url];
    if (match) {
      return new Response(JSON.stringify(match.body ?? {}), {
        status: match.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("UserBadge", () => {
  it("renders nothing when Firebase is not configured", () => {
    const { container } = render(<UserBadge auth={_auth({ configured: false })} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when user is not signed in", () => {
    const { container } = render(<UserBadge auth={_auth({ configured: true, user: null })} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows the user's email in the trigger", async () => {
    _installFetchMock({ uid: "u", email: "jane@example.com", drive: { connected: false } });
    render(<UserBadge auth={_auth({ configured: true, user: _user() })} />);
    expect(await screen.findByText("jane@example.com")).toBeInTheDocument();
  });

  it("fetches /auth/me with Authorization header", async () => {
    const fetchMock = _installFetchMock({
      uid: "u",
      email: "jane@example.com",
      drive: { connected: false },
    });
    render(<UserBadge auth={_auth({ configured: true, user: _user() })} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer fake-id-token");
  });

  it("shows a Drive connection dot when /auth/me reports connected", async () => {
    _installFetchMock({
      uid: "u",
      email: "jane@example.com",
      drive: { connected: true, folderId: "f-1", email: "jane@example.com" },
    });
    const { container } = render(<UserBadge auth={_auth({ configured: true, user: _user() })} />);
    await waitFor(() => {
      expect(container.querySelector(".user-badge__drive-dot")).toBeInTheDocument();
    });
  });

  it("opening the menu reveals Connect Drive when not connected", async () => {
    _installFetchMock({ uid: "u", email: "jane@x.y", drive: { connected: false } });
    render(<UserBadge auth={_auth({ configured: true, user: _user() })} />);
    const trigger = await screen.findByRole("button", { name: /Account menu/i });
    await userEvent.click(trigger);
    expect(screen.getByRole("menuitem", { name: /Connect Google Drive/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Sign out/i })).toBeInTheDocument();
  });

  it("menu reveals Disconnect Drive when connected", async () => {
    _installFetchMock({
      uid: "u",
      email: "jane@x.y",
      drive: { connected: true, folderId: "f-1", email: "jane@x.y" },
    });
    render(<UserBadge auth={_auth({ configured: true, user: _user() })} />);
    const trigger = await screen.findByRole("button", { name: /Account menu/i });
    await userEvent.click(trigger);
    expect(screen.getByRole("menuitem", { name: /Disconnect Google Drive/i })).toBeInTheDocument();
  });

  it("Connect Drive click POSTs to /auth/drive/connect and navigates to authorizeUrl", async () => {
    _installFetchMock(
      { uid: "u", email: "jane@x.y", drive: { connected: false } },
      {
        "/auth/drive/connect": {
          body: { authorizeUrl: "https://google/consent?state=x" },
        },
      },
    );
    const locationStub = { href: "" } as Location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: locationStub,
    });

    render(<UserBadge auth={_auth({ configured: true, user: _user() })} />);
    const trigger = await screen.findByRole("button", { name: /Account menu/i });
    await userEvent.click(trigger);
    await userEvent.click(screen.getByRole("menuitem", { name: /Connect Google Drive/i }));

    await waitFor(() => {
      expect(locationStub.href).toBe("https://google/consent?state=x");
    });
  });

  it("Disconnect Drive click POSTs /auth/drive/disconnect and refreshes status", async () => {
    let connected = true;

    const fetchMock = vi.fn(async (input: URL | RequestInfo, _init?: RequestInit) => {
      const url = input.toString();
      if (url === "/auth/me") {
        return new Response(
          JSON.stringify({
            uid: "u",
            email: "jane@x.y",
            drive: connected
              ? { connected: true, folderId: "f", email: "jane@x.y" }
              : { connected: false, folderId: null, email: null },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url === "/auth/drive/disconnect") {
        connected = false;
        return new Response(JSON.stringify({ disconnected: true }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<UserBadge auth={_auth({ configured: true, user: _user() })} />);
    const trigger = await screen.findByRole("button", { name: /Account menu/i });
    await userEvent.click(trigger);
    await userEvent.click(screen.getByRole("menuitem", { name: /Disconnect Google Drive/i }));

    await waitFor(() => {
      expect(document.querySelector(".user-badge__drive-dot")).not.toBeInTheDocument();
    });
    const disconnectCall = fetchMock.mock.calls.find(
      (c) => c[0].toString() === "/auth/drive/disconnect",
    );
    expect(disconnectCall).toBeDefined();
  });

  it("Sign out click invokes auth.signOut", async () => {
    _installFetchMock({ uid: "u", email: "jane@x.y", drive: { connected: false } });
    const auth = _auth({ configured: true, user: _user() });
    render(<UserBadge auth={auth} />);
    const trigger = await screen.findByRole("button", { name: /Account menu/i });
    await userEvent.click(trigger);
    await userEvent.click(screen.getByRole("menuitem", { name: /Sign out/i }));
    expect(auth.signOut).toHaveBeenCalledTimes(1);
  });

  it("falls back to displayName when email is null", async () => {
    _installFetchMock({ uid: "u", email: null, drive: { connected: false } });
    const user = _user(null);
    render(<UserBadge auth={_auth({ configured: true, user })} />);
    expect(await screen.findByText("Jane")).toBeInTheDocument();
  });
});
