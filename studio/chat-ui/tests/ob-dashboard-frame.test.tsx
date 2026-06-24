import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ObDashboardFrame } from "../src/a2ui/custom/ob-dashboard-frame";
import type { A2UISurface } from "../src/types";

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

function surface(): A2UISurface {
  return {
    surfaceId: "s1",
    catalogId: "openbench",
    components: new Map(),
    dataModel: {},
  };
}

describe("ObDashboardFrame", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a native dashboard ViewModel with KPIs, charts, tables, and text", () => {
    const viewModel = {
      title: "Sales Dashboard",
      description: "Uploaded sales data.",
      datasets: {
        revenue_by_region: [
          { region: "EU", revenue: 150 },
          { region: "US", revenue: 120 },
        ],
      },
      kpis: [{ label: "Total Revenue", value: 270, unit: "USD" }],
      sections: [
        {
          title: "Revenue",
          items: [
            {
              type: "chart",
              chart_type: "bar",
              title: "Revenue by Region",
              dataset: "revenue_by_region",
              x: "region",
              y: "revenue",
            },
            {
              type: "table",
              title: "Revenue Table",
              dataset: "revenue_by_region",
              columns: ["region", "revenue"],
            },
            {
              type: "text",
              title: "Summary",
              content: "EU leads the uploaded sample.",
            },
          ],
        },
      ],
    };

    const { container } = render(
      <ObDashboardFrame
        component={{ id: "dashboard", component: "ObDashboardFrame", viewModel }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("Sales Dashboard")).toBeDefined();
    expect(screen.getByText("Uploaded sales data.")).toBeDefined();
    expect(screen.getByText("Total Revenue")).toBeDefined();
    expect(screen.getByText("270")).toBeDefined();
    expect(screen.getByText("Revenue by Region")).toBeDefined();
    expect(screen.getByText("Revenue Table")).toBeDefined();
    expect(screen.getByText("EU leads the uploaded sample.")).toBeDefined();
    expect(container.querySelector(".ob-chart")).not.toBeNull();
    expect(container.querySelector(".ob-table")).not.toBeNull();
    expect(container.querySelector('[data-dashboard-renderer="a2ui"]')).not.toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("renders chart panels from dashboard ViewModel aliases", () => {
    const viewModel = {
      title: "Coffee Dashboard",
      datasets: {
        monthly_sales: [
          { month: "Jan", revenue: 100 },
          { month: "Feb", revenue: 140 },
        ],
      },
      kpis: [{ label: "Revenue", value: 240 }],
      sections: [
        {
          title: "Trends",
          charts: [
            {
              chartType: "line",
              title: "Monthly Revenue",
              datasetId: "monthly_sales",
              xField: "month",
              yField: "revenue",
            },
          ],
        },
      ],
    };

    const { container } = render(
      <ObDashboardFrame
        component={{ id: "dashboard", component: "ObDashboardFrame", viewModel }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("Monthly Revenue")).toBeDefined();
    expect(container.querySelector(".ob-chart")).not.toBeNull();
  });

  it("renders table panels with object column descriptors", () => {
    const viewModel = {
      title: "Coffee Dashboard",
      datasets: {
        top_days: [
          { tanggal: "2026-06-01", pendapatan: 1250000 },
          { tanggal: "2026-06-02", pendapatan: 980000 },
        ],
      },
      sections: [
        {
          title: "Tables",
          items: [
            {
              type: "table",
              title: "5 Hari dengan Pendapatan Tertinggi",
              dataset: "top_days",
              columns: [
                { key: "tanggal", label: "Tanggal" },
                { field: "pendapatan", header: "Pendapatan" },
              ],
            },
          ],
        },
      ],
    };

    render(
      <ObDashboardFrame
        component={{ id: "dashboard", component: "ObDashboardFrame", viewModel }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("5 Hari dengan Pendapatan Tertinggi")).toBeDefined();
    expect(screen.getByText("Tanggal")).toBeDefined();
    expect(screen.getByText("Pendapatan")).toBeDefined();
    expect(screen.getByText("2026-06-01")).toBeDefined();
    expect(screen.getByText("1,250,000")).toBeDefined();
    expect(screen.queryByText("[object Object]")).toBeNull();
  });

  it("prefers native A2UI rendering when both ViewModel and dashboardUrl exist", () => {
    const viewModel = {
      title: "Sales Dashboard",
      datasets: {},
      kpis: [{ label: "Revenue", value: 270 }],
      sections: [],
    };

    const { container } = render(
      <ObDashboardFrame
        component={{
          id: "dashboard",
          component: "ObDashboardFrame",
          viewModel,
          dashboardUrl: "/downloads/dashboard.html",
        }}
        surface={surface()}
      />,
    );

    expect(container.querySelector('[data-dashboard-renderer="a2ui"]')).not.toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("prefers native A2UI rendering when ViewModel is inside legacy properties", () => {
    const viewModel = {
      title: "Dashboard Penjualan Kopi",
      datasets: {},
      kpis: [{ label: "Revenue", value: 500 }],
      sections: [],
    };

    const { container } = render(
      <ObDashboardFrame
        component={{
          id: "dashboard",
          component: "ObDashboardFrame",
          dashboardUrl: "/downloads/kopi.html",
          properties: { viewModel },
        }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("Dashboard Penjualan Kopi")).toBeDefined();
    expect(container.querySelector('[data-dashboard-renderer="a2ui"]')).not.toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("prefers native A2UI rendering when ViewModel is a JSON string", () => {
    const viewModel = JSON.stringify({
      title: "String Dashboard",
      datasets: {},
      kpis: [{ label: "Orders", value: 42 }],
      sections: [],
    });

    const { container } = render(
      <ObDashboardFrame
        component={{
          id: "dashboard",
          component: "ObDashboardFrame",
          dashboardUrl: "/downloads/string.html",
          viewModel,
        }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("String Dashboard")).toBeDefined();
    expect(container.querySelector('[data-dashboard-renderer="a2ui"]')).not.toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("falls back to an iframe when no ViewModel is provided", () => {
    const { container } = render(
      <ObDashboardFrame
        component={{
          id: "dashboard",
          component: "ObDashboardFrame",
          title: "Legacy Dashboard",
          dashboardUrl: "/downloads/dashboard.html",
          fileName: "dashboard.html",
        }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("Legacy Dashboard")).toBeDefined();
    expect(container.querySelector('[data-dashboard-renderer="html-fallback"]')).not.toBeNull();
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toBe("/downloads/dashboard.html");
  });
});
