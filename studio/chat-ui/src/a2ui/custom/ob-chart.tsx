/**
 * ObChart — OpenBench custom chart component (Recharts).
 *
 * Supports: bar, line, pie, scatter, area chart types.
 */

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { A2UIComponentRenderer } from "../../types";
import { resolveString, resolveValue } from "../data-binding";

/**
 * Theme-matched chart palettes. Same hue order in both modes so a given series
 * keeps a consistent identity when the user toggles the theme.
 * Light: deeper saturated hues led by the light accent (#1f63c6) — reads on white.
 * Dark: brighter / pastel versions led by the dark accent (#4f9bff) — pops on #191919.
 */
const LIGHT_COLORS = [
  "#1f63c6",
  "#0f8268",
  "#b8860b",
  "#8d4bb3",
  "#c0392b",
  "#5f6f7d",
  "#2f6f8f",
  "#6b7f2a",
  "#7b5c43",
  "#4f5aa8",
];
const DARK_COLORS = [
  "#4f9bff",
  "#34d3a6",
  "#f2c14e",
  "#c08cff",
  "#ff7a7a",
  "#9bb4c4",
  "#5fd0e6",
  "#bcd36a",
  "#d6a981",
  "#8a93e0",
];

/** Reactively report whether the app is in dark mode (data-theme on <html>). */
function useIsDark(): boolean {
  const read = () => {
    if (typeof document === "undefined") return false;
    const theme = document.documentElement.getAttribute("data-theme");
    if (theme === "dark") return true;
    if (theme === "light") return false;
    return (
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches === true
    );
  };

  const [isDark, setIsDark] = useState<boolean>(read);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const update = () => setIsDark(read());

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    media?.addEventListener?.("change", update);

    return () => {
      observer.disconnect();
      media?.removeEventListener?.("change", update);
    };
  }, []);

  return isDark;
}

export const ObChart: A2UIComponentRenderer = ({ component, surface }) => {
  const isDark = useIsDark();
  const palette = isDark ? DARK_COLORS : LIGHT_COLORS;
  const axisColor = isDark ? "#9b9a97" : "#787774";
  const gridColor = isDark ? "rgba(255, 255, 255, 0.09)" : "rgba(0, 0, 0, 0.08)";
  const tooltipStyle = isDark
    ? {
        backgroundColor: "#202020",
        border: "1px solid rgba(255, 255, 255, 0.09)",
        color: "#e3e2de",
      }
    : undefined;
  const axisTick = { fill: axisColor, fontSize: 12 };

  const chartType = resolveString(component.chartType ?? "bar", surface);
  const rawData = resolveValue(component.data, surface);
  const data = Array.isArray(rawData) ? (rawData as Record<string, unknown>[]) : [];
  const options = (component.options ?? {}) as Record<string, unknown>;
  const width = (component.width as string) ?? "100%";
  const height = Number(component.height) || 300;
  const title = component.title ? resolveString(component.title, surface) : undefined;

  // Extract data keys (exclude xKey) for series
  const xKey = (options.xKey as string) ?? (data[0] ? (Object.keys(data[0])[0] ?? "name") : "name");
  const seriesKeys =
    (options.series as string[]) ?? (data[0] ? Object.keys(data[0]).filter((k) => k !== xKey) : []);

  const renderChart = () => {
    switch (chartType) {
      case "line":
        return (
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis dataKey={xKey} tick={axisTick} stroke={axisColor} />
            <YAxis tick={axisTick} stroke={axisColor} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ color: axisColor }} />
            {seriesKeys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={palette[i % palette.length]}
              />
            ))}
          </LineChart>
        );

      case "pie":
        return (
          <PieChart>
            <Pie
              data={data}
              dataKey={seriesKeys[0] ?? "value"}
              nameKey={xKey}
              cx="50%"
              cy="50%"
              outerRadius={Math.min(height / 3, 120)}
              label
            >
              {data.map((entry, i) => (
                <Cell key={String(entry[xKey] ?? i)} fill={palette[i % palette.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ color: axisColor }} />
          </PieChart>
        );

      case "scatter":
        return (
          <ScatterChart>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis dataKey={xKey} name={xKey} tick={axisTick} stroke={axisColor} />
            <YAxis dataKey={seriesKeys[0]} name={seriesKeys[0]} tick={axisTick} stroke={axisColor} />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={tooltipStyle} />
            <Scatter data={data} fill={palette[0]} />
          </ScatterChart>
        );

      case "area":
        return (
          <AreaChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis dataKey={xKey} tick={axisTick} stroke={axisColor} />
            <YAxis tick={axisTick} stroke={axisColor} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ color: axisColor }} />
            {seriesKeys.map((key, i) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                fill={palette[i % palette.length]}
                stroke={palette[i % palette.length]}
                fillOpacity={0.3}
              />
            ))}
          </AreaChart>
        );

      default: // bar
        return (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis dataKey={xKey} tick={axisTick} stroke={axisColor} />
            <YAxis tick={axisTick} stroke={axisColor} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: gridColor }} />
            <Legend wrapperStyle={{ color: axisColor }} />
            {seriesKeys.map((key, i) => (
              <Bar key={key} dataKey={key} fill={palette[i % palette.length]} />
            ))}
          </BarChart>
        );
    }
  };

  return (
    <div className="ob-chart" data-component-id={component.id} style={{ width }}>
      {title && <p className="ob-chart__title">{title}</p>}
      <ResponsiveContainer width="100%" height={height}>
        {renderChart()}
      </ResponsiveContainer>
    </div>
  );
};
