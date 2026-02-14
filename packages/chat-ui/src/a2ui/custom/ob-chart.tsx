/**
 * ObChart — OpenBench custom chart component (Recharts).
 *
 * Supports: bar, line, pie, scatter, area chart types.
 */

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

const DEFAULT_COLORS = [
  "#8884d8",
  "#82ca9d",
  "#ffc658",
  "#ff7300",
  "#0088fe",
  "#00c49f",
  "#ffbb28",
  "#ff8042",
  "#a4de6c",
  "#d0ed57",
];

export const ObChart: A2UIComponentRenderer = ({ component, surface }) => {
  const chartType = resolveString(component.chartType ?? "bar", surface);
  const rawData = resolveValue(component.data, surface);
  const data = Array.isArray(rawData) ? (rawData as Record<string, unknown>[]) : [];
  const options = (component.options ?? {}) as Record<string, unknown>;
  const width = (component.width as string) ?? "100%";
  const height = Number(component.height) || 300;
  const title = component.title ? resolveString(component.title, surface) : undefined;

  // Extract data keys (exclude xKey) for series
  const xKey = (options.xKey as string) ?? (data[0] ? Object.keys(data[0])[0]! : "name");
  const seriesKeys =
    (options.series as string[]) ?? (data[0] ? Object.keys(data[0]).filter((k) => k !== xKey) : []);

  const renderChart = () => {
    switch (chartType) {
      case "line":
        return (
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={xKey} />
            <YAxis />
            <Tooltip />
            <Legend />
            {seriesKeys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
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
              {data.map((_entry, i) => (
                <Cell key={i} fill={DEFAULT_COLORS[i % DEFAULT_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        );

      case "scatter":
        return (
          <ScatterChart>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={xKey} name={xKey} />
            <YAxis dataKey={seriesKeys[0]} name={seriesKeys[0]} />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} />
            <Scatter data={data} fill={DEFAULT_COLORS[0]} />
          </ScatterChart>
        );

      case "area":
        return (
          <AreaChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={xKey} />
            <YAxis />
            <Tooltip />
            <Legend />
            {seriesKeys.map((key, i) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                fill={DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
                stroke={DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
                fillOpacity={0.3}
              />
            ))}
          </AreaChart>
        );

      default: // bar
        return (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={xKey} />
            <YAxis />
            <Tooltip />
            <Legend />
            {seriesKeys.map((key, i) => (
              <Bar key={key} dataKey={key} fill={DEFAULT_COLORS[i % DEFAULT_COLORS.length]} />
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
