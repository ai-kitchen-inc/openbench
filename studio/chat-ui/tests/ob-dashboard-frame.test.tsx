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

  it("resolves dataset-backed KPI values with format hints", () => {
    const viewModel = {
      title: "Coffee Sales Performance Dashboard",
      datasets: {
        kpis: [{ total_revenue: 115431.58, total_transactions: 3636 }],
      },
      kpis: [
        {
          label: "Total Revenue",
          dataset_id: "kpis",
          value_column: "total_revenue",
          format: "$#,###.00",
        },
        {
          label: "Total Transactions",
          dataset_id: "kpis",
          value_column: "total_transactions",
          format: "#,###",
        },
      ],
      sections: [],
    };

    render(
      <ObDashboardFrame
        component={{ id: "dashboard", component: "ObDashboardFrame", viewModel }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("$115,431.58")).toBeDefined();
    expect(screen.getByText("3,636")).toBeDefined();
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

  it("renders KPI and chart panels from top-level layout components", () => {
    const viewModel = {
      title: "Dashboard Penjualan Kopi",
      layout: { columns: 3 },
      datasets: {
        dataset_1: [
          { month: "Jan", sales: 6398.86 },
          { month: "Feb", sales: 13215.48 },
        ],
      },
      components: [
        {
          id: "kpi_total_sales",
          type: "kpi",
          content: { title: "Total Penjualan", value: 115431.58, variant: "currency" },
        },
        {
          id: "chart_monthly_trend",
          type: "chart",
          content: {
            title: "Tren Penjualan Bulanan",
            data: "dataset_1",
            type: "line",
            x: "month",
            y: "sales",
          },
        },
      ],
      kpis: [],
      sections: [{ title: "Dashboard", items: [] }],
    };

    const { container } = render(
      <ObDashboardFrame
        component={{ id: "dashboard", component: "ObDashboardFrame", viewModel }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("Dashboard Penjualan Kopi")).toBeDefined();
    expect(screen.getByText("Total Penjualan")).toBeDefined();
    expect(screen.getByText("$115,431.58")).toBeDefined();
    expect(screen.getByText("Tren Penjualan Bulanan")).toBeDefined();
    expect(container.querySelector(".ob-chart")).not.toBeNull();
    expect(container.querySelector('[data-dashboard-renderer="a2ui"]')).not.toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("renders nested section components with inline chart view models", () => {
    const viewModel = {
      title: "Coffee Sales Performance Dashboard",
      components: [
        {
          type: "section",
          columns: 4,
          components: [
            {
              type: "kpi",
              label: "Total Revenue",
              value: 115431.58,
              value_format: "$,.2f",
            },
            {
              type: "kpi",
              label: "Total Transactions",
              value: 3636,
            },
          ],
        },
        {
          type: "section",
          columns: 2,
          components: [
            {
              type: "chart",
              view_model: {
                type: "line_chart",
                data: [
                  { label: "Jan", value: 6398.86 },
                  { label: "Feb", value: 13215.48 },
                ],
              },
              options: { title: "Monthly Revenue Trend" },
            },
            {
              type: "chart",
              view_model: {
                type: "bar_chart",
                data: [
                  { label: "Latte", value: 27866.3 },
                  { label: "Americano with Milk", value: 25269.12 },
                ],
              },
              options: { title: "Revenue by Coffee Type" },
            },
          ],
        },
      ],
      datasets: {},
      kpis: [],
      sections: [
        {
          title: "Dashboard",
          items: [
            {
              type: "section",
              components: [
                {
                  type: "chart",
                  view_model: {
                    type: "bar_chart",
                    data: [{ label: "Latte", value: 27866.3 }],
                  },
                  options: { title: "Stale Wrapped Section" },
                },
              ],
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

    expect(screen.getByText("Coffee Sales Performance Dashboard")).toBeDefined();
    expect(screen.getByText("Total Revenue")).toBeDefined();
    expect(screen.getByText("$115,431.58")).toBeDefined();
    expect(screen.getByText("Total Transactions")).toBeDefined();
    expect(screen.getByText("3,636")).toBeDefined();
    expect(screen.getByText("Monthly Revenue Trend")).toBeDefined();
    expect(screen.getByText("Revenue by Coffee Type")).toBeDefined();
    expect(screen.queryByText("Summary")).toBeNull();
    expect(container.querySelectorAll(".ob-chart").length).toBe(2);
    expect(container.querySelector('[data-dashboard-renderer="a2ui"]')).not.toBeNull();
  });

  it("renders row column props with dataset-backed chart and table", () => {
    const viewModel = {
      title: "Row Props Dashboard",
      datasets: {
        revenue_trend: [{ month: "2022-01", revenue: 1419751.89 }],
        top_products: [{ product: "Latte", revenue: 27866.3 }],
      },
      components: [
        {
          component: "row",
          columns: [
            {
              component: "kpi",
              props: { label: "Total Revenue", value: 32866573.74, format: "$0.2s" },
            },
            {
              component: "chart",
              props: {
                title: "Monthly Revenue Trend",
                dataset_id: "revenue_trend",
                chart_type: "line",
                x_axis: { property: "month", label: "Month" },
                y_axis: { property: "revenue", label: "Revenue" },
              },
            },
            {
              component: "table",
              props: {
                title: "Top Products",
                dataset_id: "top_products",
                columns: [{ key: "product" }, { key: "revenue" }],
              },
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

    expect(screen.getByText("Total Revenue")).toBeDefined();
    expect(screen.getByText("$32,866,573.74")).toBeDefined();
    expect(screen.getByText("Monthly Revenue Trend")).toBeDefined();
    expect(screen.getByText("Top Products")).toBeDefined();
    expect(container.querySelector(".ob-chart")).not.toBeNull();
    expect(container.querySelector(".ob-table")).not.toBeNull();
    expect(screen.queryByText("No chart data available")).toBeNull();
  });

  it("renders kpi_grid and Chart.js data from loose charts list", () => {
    const viewModel = {
      title: "Loose Charts Dashboard",
      charts: [
        { type: "kpi_grid", data: { values: [{ label: "Revenue", value: 123 }] } },
        {
          type: "bar",
          title: "Revenue by Product",
          data: {
            labels: ["Latte", "Americano"],
            datasets: [{ label: "Revenue", data: [123, 95] }],
          },
        },
      ],
    };

    const { container } = render(
      <ObDashboardFrame
        component={{ id: "dashboard", component: "ObDashboardFrame", viewModel }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("Revenue")).toBeDefined();
    expect(screen.getByText("123")).toBeDefined();
    expect(screen.getByText("Revenue by Product")).toBeDefined();
    expect(container.querySelector(".ob-chart")).not.toBeNull();
    expect(screen.queryByText("No chart data available")).toBeNull();
  });

  it("renders charts whose data field contains dataset and axis config", () => {
    const viewModel = {
      title: "Coffee Sales Analysis Dashboard",
      kpis: [{ label: "Total Sales", value: 115431.58 }],
      charts: [
        {
          data: { x: "Month_name", y: "sales", dataset_id: "monthly_sales" },
          type: "line",
          title: "Monthly Sales Trend",
        },
        {
          data: { dataset_id: "cash_type_sales", value: "sales", label: "cash_type" },
          type: "pie",
          title: "Sales by Payment Method",
        },
      ],
      datasets: {
        monthly_sales: [
          { Month_name: "Jan", Monthsort: 1, sales: 6398.86 },
          { Month_name: "Feb", Monthsort: 2, sales: 13215.48 },
        ],
        cash_type_sales: [
          { cash_type: "card", sales: 112245.58 },
          { cash_type: "cash", sales: 3186.0 },
        ],
      },
      sections: [
        {
          title: "Dashboard",
          items: [
            { type: "chart", title: "Monthly Sales Trend", data: [], x_field: "name", y_field: "value" },
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

    expect(screen.getByText("Monthly Sales Trend")).toBeDefined();
    expect(screen.getByText("Sales by Payment Method")).toBeDefined();
    expect(container.querySelectorAll(".ob-chart").length).toBe(2);
    expect(screen.queryByText("No chart data available")).toBeNull();
  });

  it("synthesizes chart panels from datasets when sections are empty", () => {
    const viewModel = {
      title: "Executive Sales Dashboard",
      kpis: [{ label: "Total Revenue", value: 32866573.74, format: "$0.2s" }],
      datasets: {
        kpis: [{ total_revenue: 32866573.74 }],
        revenue_by_payment: [
          { payment_method: "Wallet", revenue: 6678638.47 },
          { payment_method: "UPI", revenue: 6579441.44 },
        ],
        revenue_by_month: [
          { month: "2022-01", revenue: 1419751.89 },
          { month: "2022-02", revenue: 1266714.29 },
        ],
      },
      sections: [{ title: "Executive Summary", items: [] }],
    };

    const { container } = render(
      <ObDashboardFrame
        component={{ id: "dashboard", component: "ObDashboardFrame", viewModel }}
        surface={surface()}
      />,
    );

    expect(screen.getByText("Revenue By Payment")).toBeDefined();
    expect(screen.getByText("Revenue By Month")).toBeDefined();
    expect(container.querySelectorAll(".ob-chart").length).toBe(2);
    expect(screen.queryByText("No chart data available")).toBeNull();
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

  it("renders the exported HTML preview when both ViewModel and dashboardUrl exist", () => {
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

    expect(container.querySelector('[data-dashboard-renderer="html-export"]')).not.toBeNull();
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toBe("/downloads/dashboard.html");
  });

  it("marks native A2UI dashboards with uploaded template metadata", () => {
    const viewModel = {
      title: "Templated Dashboard",
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
          customTemplate: { source: "design.md", format: "markdown", chars: 120 },
          templateSource: "user",
          templateFormat: "markdown",
        }}
        surface={surface()}
      />,
    );

    const frame = container.querySelector('[data-dashboard-renderer="a2ui"]');
    expect(frame).not.toBeNull();
    expect(frame?.getAttribute("data-dashboard-template-source")).toBe("user");
    expect(frame?.getAttribute("data-dashboard-template-format")).toBe("markdown");
  });

  it("renders the exported HTML preview when ViewModel is inside legacy properties", () => {
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
    expect(container.querySelector('[data-dashboard-renderer="html-export"]')).not.toBeNull();
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toBe("/downloads/kopi.html");
  });

  it("renders the exported HTML preview when ViewModel is a JSON string", () => {
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
    expect(container.querySelector('[data-dashboard-renderer="html-export"]')).not.toBeNull();
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toBe("/downloads/string.html");
  });

  it("renders the exported HTML preview when no ViewModel is provided", () => {
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
    expect(container.querySelector('[data-dashboard-renderer="html-export"]')).not.toBeNull();
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toBe("/downloads/dashboard.html");
  });
});
