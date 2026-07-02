import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ObChart } from "../src/a2ui/custom/ob-chart";
import type { A2UISurface } from "../src/types";

// Capture the `fill` passed to each <Bar> so we can assert palette selection.
vi.mock("recharts", () => {
  const ChartShell = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  const Bar = ({ fill }: { fill?: string }) => <span data-testid="bar" data-fill={fill} />;
  const Empty = () => null;

  return {
    Area: Empty,
    AreaChart: ChartShell,
    Bar,
    BarChart: ChartShell,
    CartesianGrid: Empty,
    Cell: Empty,
    Legend: Empty,
    Line: Empty,
    LineChart: ChartShell,
    Pie: ChartShell,
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

function renderBarFill(): string | null {
  const { container, unmount } = render(
    <ObChart
      component={{
        id: "c1",
        component: "ObChart",
        chartType: "bar",
        data: [
          { region: "EU", revenue: 150 },
          { region: "US", revenue: 120 },
        ],
      }}
      surface={surface()}
    />,
  );
  const fill = container.querySelector('[data-testid="bar"]')?.getAttribute("data-fill") ?? null;
  // Unmount so the component's MutationObserver doesn't fire setState (outside
  // act) when a later assertion flips data-theme on the document element.
  unmount();
  return fill;
}

describe("ObChart palette", () => {
  afterEach(() => {
    document.documentElement.removeAttribute("data-theme");
    vi.restoreAllMocks();
  });

  it("uses the light-mode accent when data-theme is light", () => {
    document.documentElement.setAttribute("data-theme", "light");
    expect(renderBarFill()).toBe("#1f63c6");
  });

  it("uses the dark-mode accent when data-theme is dark", () => {
    document.documentElement.setAttribute("data-theme", "dark");
    expect(renderBarFill()).toBe("#4f9bff");
  });

  it("flips the palette between light and dark", () => {
    document.documentElement.setAttribute("data-theme", "light");
    const light = renderBarFill();
    document.documentElement.setAttribute("data-theme", "dark");
    const dark = renderBarFill();
    expect(light).not.toBe(dark);
  });
});
