from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any

from .metrics import window_indices
from .profiles import Profile


def profile_svg(
    profile: Profile,
    output: Path,
    title: str,
    windows: dict[str, list[int]],
) -> None:
    width, height = 1200, 460
    left, right, top, bottom = 72, 32, 48, 58
    plot_width, plot_height = width - left - right, height - top - bottom
    finite = [value for value in profile if math.isfinite(value)]
    ymin, ymax = min(finite), max(finite)
    padding = 0.08 * (ymax - ymin if ymax > ymin else 1.0)
    ymin -= padding
    ymax += padding

    def sx(index: float) -> float:
        return left + index * plot_width / max(len(profile) - 1, 1)

    def sx_edge(index: float) -> float:
        return left + index * plot_width / len(profile)

    def sy(value: float) -> float:
        return top + (ymax - value) * plot_height / max(ymax - ymin, 1e-12)

    colors = {
        "mp": "#d62728",
        "ip_test": "#9467bd",
        "off_primary": "#1f77b4",
        "off_control": "#2ca02c",
    }
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="27" text-anchor="middle" font-family="Arial" font-size="18">{html.escape(title)}</text>',
    ]
    for name, window in windows.items():
        indices = window_indices(window, len(profile))
        runs: list[list[int]] = []
        for index in indices:
            if not runs or index != runs[-1][-1] + 1:
                runs.append([index])
            else:
                runs[-1].append(index)
        for run in runs:
            x = sx_edge(run[0])
            x2 = sx_edge(run[-1] + 1)
            lines.append(
                f'<rect x="{x:.2f}" y="{top}" width="{max(x2 - x, 1):.2f}" height="{plot_height}" '
                f'fill="{colors.get(name, "#999")}" opacity="0.12"/>'
            )
    points = " ".join(
        f"{sx(index):.2f},{sy(value):.2f}" for index, value in enumerate(profile)
    )
    lines.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="black"/>',
            f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="black"/>',
            f'<polyline points="{points}" fill="none" stroke="#111" stroke-width="1.1"/>',
            f'<text x="{left + plot_width / 2}" y="{height - 18}" text-anchor="middle" font-family="Arial" font-size="13">Template-coordinate phase bin</text>',
        ]
    )
    legend_x = left
    for name in ("mp", "ip_test", "off_primary", "off_control"):
        lines.append(
            f'<text x="{legend_x}" y="{height - 39}" font-family="Arial" font-size="11" fill="{colors[name]}">{html.escape(name)}</text>'
        )
        legend_x += 120
    lines.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mjd_svg(rows: list[dict[str, Any]], output: Path) -> None:
    if not rows:
        return
    points = [
        (
            float(row["mjd"]),
            float(row["mean_mp_energy_primary"]),
            str(row.get("analysis_role", "")),
        )
        for row in rows
        if row.get("mjd") not in (None, "")
        and row.get("mean_mp_energy_primary") not in (None, "")
    ]
    if not points:
        return
    width, height = 1000, 520
    left, right, top, bottom = 86, 34, 54, 72
    plot_width, plot_height = width - left - right, height - top - bottom
    xvalues = [point[0] for point in points]
    yvalues = [point[1] for point in points]
    xmin, xmax = min(xvalues), max(xvalues)
    ymin, ymax = min(yvalues), max(yvalues)
    if xmin == xmax:
        xmin -= 0.5
        xmax += 0.5
    if ymin == ymax:
        ymin -= 0.5
        ymax += 0.5

    def sx(value: float) -> float:
        return left + (value - xmin) * plot_width / (xmax - xmin)

    def sy(value: float) -> float:
        return top + (ymax - value) * plot_height / (ymax - ymin)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="28" text-anchor="middle" font-family="Arial" font-size="18">PSR J0627+0706: template-aligned relative pulse energy</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="black"/>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="black"/>',
    ]
    for mjd, energy, role in points:
        high_frequency = "high_frequency" in role
        fill = "white" if high_frequency else "#1f77b4"
        stroke = "#d62728" if high_frequency else "#1f77b4"
        lines.append(
            f'<circle cx="{sx(mjd):.2f}" cy="{sy(energy):.2f}" r="6" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
    lines.extend(
        [
            f'<text x="{left + plot_width / 2}" y="{height - 25}" text-anchor="middle" font-family="Arial" font-size="14">MJD</text>',
            f'<text x="22" y="{top + plot_height / 2}" transform="rotate(-90 22,{top + plot_height / 2})" text-anchor="middle" font-family="Arial" font-size="14">Relative pulse energy (arbitrary units; not mJy)</text>',
            f'<text x="{left}" y="{height - 48}" font-family="Arial" font-size="11">Open red markers: high-frequency-limited review; excluded from broadband pool.</text>',
            "</svg>",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
