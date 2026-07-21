import { useMemo } from "react";
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
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PanelData, PanelSpec } from "../api";
import { usePanelData } from "./usePanelData";
import { PanelFrame } from "./PanelFrame";

/* Categorical palettes validated with the dataviz six-checks script
 * (lightness band, chroma floor, CVD separation, normal-vision floor,
 * contrast vs surface) for each mode's surface. Same hue order in both
 * modes so a series keeps its identity across the theme toggle. Light
 * mode reuses the SDK ObChart hues so canvas charts match chat charts. */
const LIGHT_COLORS = ["#1f63c6", "#0f8268", "#b8860b", "#8d4bb3", "#c0392b"];
const DARK_COLORS = ["#3d7fd9", "#199d77", "#b3822a", "#9a6ad0", "#cf5f5f"];

function isDarkTheme(): boolean {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

interface ChartShape {
  records: Record<string, string | number | null>[];
  xKey: string;
  seriesKeys: string[];
}

/** First column = x/label, remaining numeric columns = series (agent contract). */
function toChartShape(data: PanelData, panel: PanelSpec): ChartShape {
  const xKey = panel.x && data.columns.includes(panel.x) ? panel.x : data.columns[0];
  const preferred = (panel.y ?? []).filter((column) => data.columns.includes(column));
  const seriesKeys = preferred.length
    ? preferred
    : data.columns.filter((column) => column !== xKey);
  const records = data.rows.map((row) => {
    const record: Record<string, string | number | null> = {};
    data.columns.forEach((column, index) => {
      const value = row[index];
      record[column] =
        typeof value === "boolean" ? String(value) : (value as string | number | null);
    });
    return record;
  });
  return { records, xKey, seriesKeys };
}

const AXIS_FONT = 11;

export function ChartPanel({ panel }: { panel: PanelSpec }) {
  const { data, error, isLoading, reload } = usePanelData(panel.id, panel.sql);
  const dark = isDarkTheme();
  const colors = dark ? DARK_COLORS : LIGHT_COLORS;
  const inkMuted = dark ? "#8f8f8c" : "#8a8a86";
  const gridStroke = dark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.06)";
  const surface = dark ? "#1f1f1e" : "#ffffff";

  const shape = useMemo(() => (data ? toChartShape(data, panel) : null), [data, panel]);

  const meta = data?.truncated ? `first ${data.rows.length} rows` : undefined;

  return (
    <PanelFrame title={panel.title} isLoading={isLoading} error={error} onRetry={reload} meta={meta}>
      {shape && shape.records.length === 0 ? (
        <div className="panel__empty">No rows.</div>
      ) : (
        shape && (
          <div className="panel__chart">
            <ResponsiveContainer width="100%" height="100%">
              {renderChart(panel, shape, { colors, inkMuted, gridStroke, surface })}
            </ResponsiveContainer>
          </div>
        )
      )}
    </PanelFrame>
  );
}

function renderChart(
  panel: PanelSpec,
  shape: ChartShape,
  theme: { colors: string[]; inkMuted: string; gridStroke: string; surface: string },
) {
  const { records, xKey, seriesKeys } = shape;
  const { colors, inkMuted, gridStroke, surface } = theme;
  const axisProps = {
    stroke: inkMuted,
    fontSize: AXIS_FONT,
    tickLine: false,
    axisLine: false,
  } as const;
  const tooltipProps = {
    contentStyle: {
      background: surface,
      border: "1px solid " + gridStroke,
      borderRadius: 6,
      fontSize: 12,
    },
    cursor: { fill: gridStroke },
  } as const;
  const showLegend = seriesKeys.length >= 2;

  if (panel.type === "pie") {
    const valueKey = seriesKeys[0];
    return (
      <PieChart>
        <Tooltip {...tooltipProps} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Pie
          data={records}
          dataKey={valueKey}
          nameKey={xKey}
          innerRadius="55%"
          outerRadius="85%"
          paddingAngle={2}
          stroke={surface}
          strokeWidth={2}
        >
          {records.map((_, index) => (
            <Cell key={index} fill={colors[index % colors.length]} />
          ))}
        </Pie>
      </PieChart>
    );
  }

  if (panel.type === "line") {
    return (
      <LineChart data={records} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={gridStroke} vertical={false} />
        <XAxis dataKey={xKey} {...axisProps} />
        <YAxis {...axisProps} width={44} />
        <Tooltip {...tooltipProps} cursor={{ stroke: inkMuted, strokeDasharray: "3 3" }} />
        {showLegend && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {seriesKeys.map((key, index) => (
          <Line
            key={key}
            type="monotone"
            dataKey={key}
            stroke={colors[index % colors.length]}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        ))}
      </LineChart>
    );
  }

  if (panel.type === "area") {
    return (
      <AreaChart data={records} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={gridStroke} vertical={false} />
        <XAxis dataKey={xKey} {...axisProps} />
        <YAxis {...axisProps} width={44} />
        <Tooltip {...tooltipProps} cursor={{ stroke: inkMuted, strokeDasharray: "3 3" }} />
        {showLegend && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {seriesKeys.map((key, index) => (
          <Area
            key={key}
            type="monotone"
            dataKey={key}
            stroke={colors[index % colors.length]}
            strokeWidth={2}
            fill={colors[index % colors.length]}
            fillOpacity={0.12}
          />
        ))}
      </AreaChart>
    );
  }

  // Default: bar.
  return (
    <BarChart data={records} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2}>
      <CartesianGrid stroke={gridStroke} vertical={false} />
      <XAxis dataKey={xKey} {...axisProps} />
      <YAxis {...axisProps} width={44} />
      <Tooltip {...tooltipProps} />
      {showLegend && <Legend wrapperStyle={{ fontSize: 12 }} />}
      {seriesKeys.map((key, index) => (
        <Bar
          key={key}
          dataKey={key}
          fill={colors[index % colors.length]}
          radius={[4, 4, 0, 0]}
          maxBarSize={40}
        />
      ))}
    </BarChart>
  );
}
