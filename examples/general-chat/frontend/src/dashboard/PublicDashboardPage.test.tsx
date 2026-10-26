import "@testing-library/jest-dom/vitest";
import { act, render, screen } from "@testing-library/react";
import { PublicDashboardPage } from "./PublicDashboardPage";

vi.mock("recharts", () => {
  const Shell = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const Empty = () => null;
  return {
    Area: Empty,
    AreaChart: Shell,
    Bar: Empty,
    BarChart: Shell,
    CartesianGrid: Empty,
    Cell: Empty,
    Legend: Empty,
    Line: Empty,
    LineChart: Shell,
    Pie: Empty,
    PieChart: Shell,
    ResponsiveContainer: Shell,
    Scatter: Empty,
    ScatterChart: Shell,
    Tooltip: Empty,
    XAxis: Empty,
    YAxis: Empty,
  };
});

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  listeners = new Map<string, Set<(event: MessageEvent<string>) => void>>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(listener);
  }

  emit(type: string, data: unknown) {
    const event = { data: JSON.stringify(data) } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  close() {
    this.closed = true;
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const payload = {
  id: "abcdef123456",
  title: "Penjualan",
  description: "Per wilayah",
  version: 1,
  refreshedAt: "2026-10-12T08:00:00+00:00",
  viewModel: { title: "Penjualan", kpis: [{ label: "Total", value: 15 }], sections: [] },
};

describe("PublicDashboardPage", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads the snapshot, subscribes, and applies pushed updates", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        expect(String(input)).toBe("/d/abcdef123456/data");
        return jsonResponse(payload);
      }),
    );
    render(<PublicDashboardPage dashboardId="abcdef123456" />);
    expect((await screen.findAllByText("Penjualan")).length).toBeGreaterThan(0);
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(document.title).toBe("Penjualan");

    const source = FakeEventSource.instances[0];
    expect(source.url).toBe("/d/abcdef123456/events");
    act(() => source.onopen?.());
    expect(screen.getByRole("status")).toHaveAttribute("data-live-state", "live");

    act(() => {
      source.emit("update", {
        ...payload,
        version: 2,
        viewModel: { ...payload.viewModel, kpis: [{ label: "Total", value: 99 }] },
      });
    });
    expect(screen.getByText("99")).toBeInTheDocument();
    expect(screen.queryByText("15")).not.toBeInTheDocument();

    act(() => source.emit("closed", { id: "abcdef123456", reason: "unpublished" }));
    expect(source.closed).toBe(true);
    expect(screen.getByRole("status")).toHaveAttribute("data-live-state", "closed");
    expect(screen.getByText("Dasbor tidak tersedia lagi")).toBeInTheDocument();
  });

  it("rebuilds the stream after 45 s without a ping", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(payload)));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<PublicDashboardPage dashboardId="abcdef123456" />);
      expect((await screen.findAllByText("Penjualan")).length).toBeGreaterThan(0);
      expect(FakeEventSource.instances).toHaveLength(1);
      act(() => FakeEventSource.instances[0].onopen?.());
      // Pings keep it alive...
      act(() => vi.advanceTimersByTime(30_000));
      act(() => FakeEventSource.instances[0].emit("ping", {}));
      act(() => vi.advanceTimersByTime(30_000));
      expect(FakeEventSource.instances).toHaveLength(1);
      // ...silence does not.
      act(() => vi.advanceTimersByTime(50_000));
      expect(FakeEventSource.instances).toHaveLength(2);
      expect(FakeEventSource.instances[0].closed).toBe(true);
      expect(screen.getByRole("status")).toHaveAttribute("data-live-state", "offline");
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows not-found for a private or missing dashboard", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "nope" }, 404)));
    render(<PublicDashboardPage dashboardId="abcdef123456" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Dasbor tidak ditemukan.");
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
