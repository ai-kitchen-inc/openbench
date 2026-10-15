import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ObDashboardFrame } from "../src/a2ui/custom/ob-dashboard-frame";
import type { A2UISurface, DashboardActions, LiveDashboardEvent } from "../src/types";

vi.mock("recharts", () => {
  const ChartShell = ({ children }: { children?: ReactNode }) => (
    <div data-testid="recharts-shell">{children}</div>
  );
  const Empty = () => null;
  return {
    Area: Empty,
    AreaChart: ChartShell,
    Bar: Empty,
    BarChart: ChartShell,
    CartesianGrid: Empty,
    Cell: Empty,
    Legend: Empty,
    Line: Empty,
    LineChart: ChartShell,
    Pie: Empty,
    PieChart: ChartShell,
    ResponsiveContainer: ChartShell,
    Scatter: Empty,
    ScatterChart: ChartShell,
    Tooltip: Empty,
    XAxis: Empty,
    YAxis: Empty,
  };
});

const ctx = vi.hoisted(() => ({
  current: null as { dashboardActions?: DashboardActions } | null,
}));

vi.mock("../src/components/ChatProvider", () => ({
  useChatContextOptional: () => ctx.current,
}));

function surface(): A2UISurface {
  return { surfaceId: "s1", catalogId: "openbench", components: new Map(), dataModel: {} };
}

const bakedViewModel = {
  title: "Penjualan",
  kpis: [{ label: "Total", value: 15 }],
  sections: [],
};

describe("ObDashboardFrame live mode", () => {
  const handlers = new Map<string, (event: LiveDashboardEvent) => void>();
  const unsubscribe = vi.fn();
  const subscribeLive = vi.fn((id: string, onEvent: (event: LiveDashboardEvent) => void) => {
    handlers.set(id, onEvent);
    return unsubscribe;
  });
  const refreshLive = vi.fn(async () => {});

  beforeEach(() => {
    handlers.clear();
    unsubscribe.mockClear();
    subscribeLive.mockClear();
    refreshLive.mockClear();
    ctx.current = { dashboardActions: { subscribeLive, refreshLive } };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderLive(extra: Record<string, unknown> = {}) {
    return render(
      <ObDashboardFrame
        component={{
          id: "dash",
          component: "ObDashboardFrame",
          properties: {
            title: "Penjualan",
            viewModel: bakedViewModel,
            dashboardId: "abcdef123456",
            live: true,
            refreshIntervalSeconds: 30,
            ...extra,
          },
        }}
        surface={surface()}
      />,
    );
  }

  it("subscribes by dashboard id and shows the connecting badge", () => {
    renderLive();
    expect(subscribeLive).toHaveBeenCalledWith("abcdef123456", expect.any(Function));
    const badge = screen.getByRole("status");
    expect(badge.getAttribute("data-live-state")).toBe("connecting");
    expect(screen.getByText("15")).toBeDefined();
  });

  it("replaces the baked ViewModel when an update arrives", () => {
    renderLive();
    act(() => {
      handlers.get("abcdef123456")?.({
        type: "update",
        version: 2,
        viewModel: { title: "Penjualan", kpis: [{ label: "Total", value: 99 }], sections: [] },
        refreshedAt: "2026-10-12T08:00:00+00:00",
      });
    });
    expect(screen.getByText("99")).toBeDefined();
    expect(screen.queryByText("15")).toBeNull();
    expect(screen.getByRole("status").getAttribute("data-live-state")).toBe("live");
    expect(screen.getByRole("status").textContent).toContain("Live");
  });

  it("marks the dashboard unavailable on closed and unsubscribes on unmount", () => {
    const { unmount } = renderLive();
    act(() => {
      handlers.get("abcdef123456")?.({ type: "closed", reason: "deleted" });
    });
    expect(screen.getByRole("status").getAttribute("data-live-state")).toBe("unavailable");
    expect(screen.queryByRole("button", { name: "Refresh data" })).toBeNull();
    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it("calls refreshLive from the badge button", async () => {
    renderLive();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Refresh data" }));
    });
    expect(refreshLive).toHaveBeenCalledWith("abcdef123456");
  });

  it("uses host labels when provided", () => {
    ctx.current = {
      dashboardActions: {
        subscribeLive,
        refreshLive,
        liveLabels: { connecting: "Menghubungkan…", refresh: "Muat ulang data" },
      },
    };
    renderLive();
    expect(screen.getByText("Menghubungkan…")).toBeDefined();
    expect(screen.getByRole("button", { name: "Muat ulang data" })).toBeDefined();
  });

  it("does not subscribe without the live flag or without a host transport", () => {
    renderLive({ live: false });
    expect(subscribeLive).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();

    ctx.current = null;
    render(
      <ObDashboardFrame
        component={{
          id: "dash2",
          component: "ObDashboardFrame",
          properties: { title: "X", viewModel: bakedViewModel, dashboardId: "abcdef123456", live: true },
        }}
        surface={surface()}
      />,
    );
    expect(subscribeLive).not.toHaveBeenCalled();
    // Still renders the baked snapshot.
    expect(screen.getAllByText("15").length).toBeGreaterThan(0);
  });
});
