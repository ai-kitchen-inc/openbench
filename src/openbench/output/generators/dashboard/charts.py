"""Inline SVG chart rendering for dashboard panels.

Pure functions that turn ``(label, value)`` point lists into self-contained
SVG markup styled by the dashboard stylesheet. No external charting library.
"""

from __future__ import annotations

import math
from typing import Any

from openbench.output.generators.dashboard.datasets import _number
from openbench.output.generators.dashboard.formatting import _escape, _format_value


def _chart_points(records: list[dict[str, Any]], x_key: str, y_key: str) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    for idx, row in enumerate(records):
        y = _number(row.get(y_key))
        if y is None:
            continue
        label = str(row.get(x_key) if row.get(x_key) is not None else idx + 1)
        points.append((label, y))
    return points[:24]


def _render_chart_svg(
    chart_type: str, records: list[dict[str, Any]], *, x_key: str, y_key: str
) -> str:
    points = _chart_points(records, x_key, y_key)
    if not points:
        return '<div class="ob-empty">No chart data available.</div>'
    normalized = chart_type.lower()
    if normalized in {"bar_horizontal", "horizontal_bar", "hbar", "column"}:
        normalized = "bar"
    if normalized == "line":
        return _render_line_svg(points, area=False)
    if normalized == "area":
        return _render_line_svg(points, area=True)
    if normalized == "pie":
        return _render_pie_svg(points)
    if normalized == "scatter":
        return _render_scatter_svg(points)
    return _render_bar_svg(points)


def _render_bar_svg(points: list[tuple[str, float]]) -> str:
    width = 720
    height = 300
    left = 42
    bottom = 44
    top = 18
    right = 16
    chart_w = width - left - right
    chart_h = height - top - bottom
    max_val = max([abs(v) for _, v in points] + [1])
    gap = 8
    bar_w = max(8, (chart_w - gap * (len(points) - 1)) / max(len(points), 1))
    bars: list[str] = []
    labels: list[str] = []
    for idx, (label, value) in enumerate(points):
        x = left + idx * (bar_w + gap)
        h = abs(value) / max_val * chart_h
        y = top + chart_h - h
        bars.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{h:.2f}" rx="3" />')
        labels.append(
            f'<text x="{x + bar_w / 2:.2f}" y="{height - 18}" text-anchor="middle">'
            f"{_escape(_short_label(label))}</text>"
        )
    axis = (
        f'<line x1="{left}" y1="{top + chart_h}" x2="{width - right}" y2="{top + chart_h}" />'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" />'
        f'<text x="{left - 8}" y="{top + 10}" text-anchor="end">{_escape(_format_value(max_val))}</text>'
    )
    return _svg(width, height, axis + "".join(bars) + "".join(labels), "bar")


def _render_line_svg(points: list[tuple[str, float]], *, area: bool) -> str:
    width = 720
    height = 300
    left = 42
    bottom = 42
    top = 18
    right = 18
    chart_w = width - left - right
    chart_h = height - top - bottom
    values = [v for _, v in points]
    min_val = min(values + [0])
    max_val = max(values + [1])
    span = max(max_val - min_val, 1)
    coords: list[tuple[float, float]] = []
    for idx, (_, value) in enumerate(points):
        x = left + (idx / max(len(points) - 1, 1)) * chart_w
        y = top + (max_val - value) / span * chart_h
        coords.append((x, y))
    path_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    axis_y = top + chart_h
    axis = (
        f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" />'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{axis_y}" />'
    )
    fill = ""
    if area and coords:
        first_x, _ = coords[0]
        last_x, _ = coords[-1]
        fill = (
            f'<polygon class="area" points="{first_x:.2f},{axis_y:.2f} '
            f'{path_points} {last_x:.2f},{axis_y:.2f}" />'
        )
    circles = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" />' for x, y in coords)
    labels = "".join(
        f'<text x="{x:.2f}" y="{height - 16}" text-anchor="middle">{_escape(_short_label(label))}</text>'
        for (label, _), (x, _y) in zip(
            points[:: max(1, len(points) // 6)], coords[:: max(1, len(points) // 6)], strict=False
        )
    )
    return _svg(
        width,
        height,
        axis + fill + f'<polyline points="{path_points}" />' + circles + labels,
        "line",
    )


def _render_scatter_svg(points: list[tuple[str, float]]) -> str:
    width = 720
    height = 300
    left = 42
    bottom = 42
    top = 18
    right = 18
    chart_w = width - left - right
    chart_h = height - top - bottom
    values = [value for _, value in points]
    max_val = max(values + [1])
    min_val = min(values + [0])
    span = max(max_val - min_val, 1)
    circles: list[str] = []
    for idx, (_label, value) in enumerate(points):
        x = left + (idx / max(len(points) - 1, 1)) * chart_w
        y = top + (max_val - value) / span * chart_h
        circles.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" />')
    axis_y = top + chart_h
    axis = (
        f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" />'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{axis_y}" />'
    )
    return _svg(width, height, axis + "".join(circles), "scatter")


def _render_pie_svg(points: list[tuple[str, float]]) -> str:
    total = sum(abs(value) for _, value in points) or 1
    width = 720
    height = 300
    cx = 150
    cy = 145
    radius = 96
    start_angle = -90.0
    paths: list[str] = []
    legend: list[str] = []
    for idx, (label, value) in enumerate(points[:10]):
        fraction = abs(value) / total
        end_angle = start_angle + fraction * 360
        paths.append(_pie_slice(cx, cy, radius, start_angle, end_angle, idx))
        legend.append(
            '<div class="ob-legend__item">'
            f'<span style="--i:{idx}"></span><strong>{_escape(_short_label(label, 24))}</strong>'
            f"<em>{_escape(_format_value(value))}</em></div>"
        )
        start_angle = end_angle
    svg = _svg(width, height, "".join(paths), "pie")
    return f'<div class="ob-pie-layout">{svg}<div class="ob-legend">{"".join(legend)}</div></div>'


def _pie_slice(cx: int, cy: int, radius: int, start: float, end: float, idx: int) -> str:
    start_rad = math.radians(start)
    end_rad = math.radians(end)
    x1 = cx + radius * math.cos(start_rad)
    y1 = cy + radius * math.sin(start_rad)
    x2 = cx + radius * math.cos(end_rad)
    y2 = cy + radius * math.sin(end_rad)
    large_arc = 1 if end - start > 180 else 0
    return (
        f'<path class="slice slice-{idx % 10}" '
        f'd="M {cx} {cy} L {x1:.2f} {y1:.2f} A {radius} {radius} 0 {large_arc} 1 '
        f'{x2:.2f} {y2:.2f} Z" />'
    )


def _svg(width: int, height: int, body: str, chart_class: str) -> str:
    return (
        f'<svg class="ob-chart ob-chart--{chart_class}" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="Dashboard chart">'
        f"{body}</svg>"
    )


def _short_label(value: str, limit: int = 12) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[: max(0, limit - 1)]}..."
