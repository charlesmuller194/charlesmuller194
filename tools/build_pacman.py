"""Build the Pac-Man board: pacman_dark.svg and pacman_light.svg.

Pac-Man snakes through the last year of the contribution calendar
(cache/calendar.json, written by tools/fetch_stats.py) row by row, eating
every square. The counter in the header climbs as he eats, then the board
resets and the loop starts over. Everything is SMIL animation, so it plays
inside a README <img> without any JavaScript.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WIDTH = 1018
HEIGHT = 224
CELL = 14
PITCH = 18
GRID_X = 54
GRID_Y = 62
STEP = 0.07          # seconds per square
HOLD = 3.0           # seconds the empty board stays up before the loop restarts
FONT = "ConsolasFallback,Consolas,Menlo,'DejaVu Sans Mono',monospace"

LEVELS = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]
PALETTES = {
    "dark": {
        "bg": "#161b22", "border": "#30363d", "fg": "#c9d1d9", "muted": "#7d8590",
        "cells": ["#21262d", "#0e4429", "#006d32", "#26a641", "#39d353"],
        "eaten": "#1b2027", "pac": "#f2cc60",
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "fg": "#24292f", "muted": "#57606a",
        "cells": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "eaten": "#f3f4f6", "pac": "#d4a017",
    },
}

MOUTH_OPEN = "M0,0 L8.5,-5.5 A10,10 0 1,0 8.5,5.5 Z"
MOUTH_HALF = "M0,0 L9.6,-2.8 A10,10 0 1,0 9.6,2.8 Z"
MOUTH_SHUT = "M0,0 L10,-0.2 A10,10 0 1,0 10,0.2 Z"


def load_calendar() -> list[list[dict | None]]:
    """Return weeks as lists of 7 slots (None where the calendar has no day)."""
    data = json.loads((ROOT / "cache" / "calendar.json").read_text())
    weeks = []
    for week in data["weeks"]:
        slots: list[dict | None] = [None] * 7
        for day in week["contributionDays"]:
            slots[day["weekday"]] = day
        weeks.append(slots)
    return weeks


def cell_xy(w: int, d: int) -> tuple[int, int]:
    return GRID_X + w * PITCH, GRID_Y + d * PITCH


def route(n_weeks: int) -> list[tuple[int, int]]:
    """Row by row, alternating direction, so Pac-Man never jumps."""
    path = []
    for d in range(7):
        cols = range(n_weeks) if d % 2 == 0 else range(n_weeks - 1, -1, -1)
        path += [(w, d) for w in cols]
    return path


def month_labels(weeks: list[list[dict | None]]) -> list[tuple[int, str]]:
    labels, last = [], -9
    prev_month = None
    for w, slots in enumerate(weeks):
        first = next((s for s in slots if s), None)
        if not first:
            continue
        month = dt.date.fromisoformat(first["date"]).month
        if month != prev_month:
            if w - last >= 3 and w < len(weeks) - 1:
                labels.append((w, dt.date(2000, month, 1).strftime("%b")))
                last = w
            prev_month = month
    return labels


def build(theme: str, weeks: list[list[dict | None]]) -> str:
    c = PALETTES[theme]
    path = route(len(weeks))
    total_time = len(path) * STEP + HOLD
    T = f"{total_time:.3f}s"

    def kt(seconds: float) -> str:
        return f"{seconds / total_time:.5f}"

    out = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="{FONT}">',
        "<style>@font-face { font-family: 'ConsolasFallback'; src: local('Consolas'); size-adjust: 109%; }",
        "text, tspan {white-space: pre;}</style>",
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="15" '
        f'fill="{c["bg"]}" stroke="{c["border"]}"/>',
    ]

    # Squares, each turning to "eaten" the moment Pac-Man reaches it.
    eaten_at: list[tuple[float, int]] = []
    out.append("<g>")
    for i, (w, d) in enumerate(path):
        day = weeks[w][d]
        if not day:
            continue
        x, y = cell_xy(w, d)
        level = LEVELS.index(day["contributionLevel"]) if day["contributionLevel"] in LEVELS else 0
        t = i * STEP + STEP / 2
        eaten_at.append((t, day["contributionCount"]))
        out.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="3" fill="{c["cells"][level]}">'
            f'<animate attributeName="fill" values="{c["cells"][level]};{c["eaten"]}" '
            f'keyTimes="0;{kt(t)}" dur="{T}" calcMode="discrete" repeatCount="indefinite"/></rect>'
        )
    out.append("</g>")

    # Header counter: one tspan per distinct running total, shown in turn.
    steps: list[tuple[float, int]] = [(0.0, 0)]
    running = 0
    for t, n in eaten_at:
        if n:
            running += n
            steps.append((t, running))
    out.append(f'<text y="31" font-size="15px" fill="{c["fg"]}">')
    for k, (t0, value) in enumerate(steps):
        t1 = steps[k + 1][0] if k + 1 < len(steps) else None
        if k == 0:
            vals, keys = ("visible;hidden", f"0;{kt(t1)}") if t1 else ("visible", "0")
        elif t1 is None:
            vals, keys = "hidden;visible", f"0;{kt(t0)}"
        else:
            vals, keys = "hidden;visible;hidden", f"0;{kt(t0)};{kt(t1)}"
        out.append(
            f'<tspan x="24" visibility="{"visible" if k == 0 else "hidden"}">'
            f'<animate attributeName="visibility" values="{vals}" keyTimes="{keys}" dur="{T}" '
            f'calcMode="discrete" repeatCount="indefinite"/>{value:>5,}</tspan>'
        )
    out.append(f'<tspan x="78">contributions in the last year</tspan></text>')

    # Month and weekday labels, legend.
    out.append(f'<g font-size="13px" fill="{c["muted"]}">')
    for w, name in month_labels(weeks):
        out.append(f'<text x="{GRID_X + w * PITCH}" y="{GRID_Y - 10}">{name}</text>')
    for d, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        out.append(f'<text x="18" y="{GRID_Y + d * PITCH + 11}">{name}</text>')
    grid_right = GRID_X + (len(weeks) - 1) * PITCH + CELL
    legend_y = GRID_Y + 7 * PITCH + 10
    legend_x = grid_right - 4 * 13 * 0.6 - 8 - (5 * PITCH - (PITCH - CELL))
    out.append(f'<text x="{legend_x - 8:.1f}" y="{legend_y + 11}" text-anchor="end">Less</text>')
    for lvl in range(5):
        out.append(f'<rect x="{legend_x + lvl * PITCH:.1f}" y="{legend_y}" width="{CELL}" height="{CELL}" '
                   f'rx="3" fill="{c["cells"][lvl]}"/>')
    out.append(f'<text x="{grid_right}" y="{legend_y + 11}" text-anchor="end">More</text>')
    out.append("</g>")

    # Pac-Man: an outer group slides square to square, an inner group flips
    # him to face the direction of travel, and his mouth chomps on its own clock.
    positions, key_times = [], []
    for i, (w, d) in enumerate(path):
        x, y = cell_xy(w, d)
        positions.append(f"{x + CELL / 2:g} {y + CELL / 2:g}")
        key_times.append(kt(i * STEP))
    last_x, last_y = positions[-1].split()
    positions.append(f"{last_x} {last_y}")
    key_times.append(kt(len(path) * STEP))
    positions.append(f"{last_x} {last_y}")
    key_times.append("1")
    face, face_keys = [], []
    for d in range(7):
        face.append("1 1" if d % 2 == 0 else "-1 1")
        face_keys.append(kt(d * len(weeks) * STEP))
    face_keys[0] = "0"
    out += [
        "<g>",
        f'<animateTransform attributeName="transform" type="translate" values="{";".join(positions)}" '
        f'keyTimes="{";".join(key_times)}" dur="{T}" calcMode="linear" repeatCount="indefinite"/>',
        "<g>",
        f'<animateTransform attributeName="transform" type="scale" values="{";".join(face)}" '
        f'keyTimes="{";".join(face_keys)}" dur="{T}" calcMode="discrete" repeatCount="indefinite"/>',
        f'<path fill="{c["pac"]}" d="{MOUTH_OPEN}">'
        f'<animate attributeName="d" values="{MOUTH_OPEN};{MOUTH_HALF};{MOUTH_SHUT};{MOUTH_HALF};{MOUTH_OPEN}" '
        f'dur="0.28s" repeatCount="indefinite"/></path>',
        f'<circle cx="1.5" cy="-5" r="1.6" fill="{c["bg"]}"/>',
        "</g>",
        "</g>",
        "</svg>",
        "",
    ]
    return "\n".join(out)


def main() -> None:
    weeks = load_calendar()
    for theme in PALETTES:
        (ROOT / f"pacman_{theme}.svg").write_text(build(theme, weeks))
    print(f"pac-man board built ({len(weeks)} weeks)")


if __name__ == "__main__":
    main()
