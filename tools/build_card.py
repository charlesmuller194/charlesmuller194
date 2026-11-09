"""Build the neofetch-style profile card: dark_mode.svg and light_mode.svg.

Inputs:
    profile.json          the rows of the card (edit this to change the text)
    assets/ascii-*.txt    the portrait, made by tools/make_ascii.py
    cache/stats.json      numbers written by tools/fetch_stats.py

Every row is padded with dot leaders to exactly PANEL_COLS characters, and each
line is drawn with textLength, so columns stay aligned whatever monospace font
the viewer's machine falls back to.
"""

from __future__ import annotations

import datetime as dt
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WIDTH = 1018
MARGIN = 15
ADVANCE = 0.6             # character width in em for the monospace stack
CELL_ASPECT = 1.85        # must match tools/make_ascii.py
ART_WIDTH = 414
PANEL_X = MARGIN + ART_WIDTH + 18
PANEL_FONT = 16
PANEL_COLS = 58
ROW_H = 20
PAD_Y = 31                # baseline of the first panel row

PALETTES = {
    "dark": {
        "bg": "#161b22", "border": "#30363d", "fg": "#c9d1d9", "art": "#b1bac4",
        "key": "#d2a8ff", "value": "#a5d6ff", "dots": "#5c6670",
        "add": "#3fb950", "del": "#f85149",
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "fg": "#24292f", "art": "#24292f",
        "key": "#8250df", "value": "#0550ae", "dots": "#8c959f",
        "add": "#1a7f37", "del": "#cf222e",
    },
}


class Row:
    """A line of the panel built from segments; `fill` runs stretch to fit."""

    def __init__(self) -> None:
        self.parts: list[tuple[str, str | None, bool]] = []

    def add(self, text: str, cls: str | None = None) -> "Row":
        self.parts.append((text, cls, False))
        return self

    def key(self, dotted: str) -> "Row":
        for i, piece in enumerate(dotted.split(".")):
            if i:
                self.add(".")
            self.add(piece, "key")
        return self

    def fill(self) -> "Row":
        self.parts.append(("", "dots", True))
        return self

    def rule(self) -> "Row":
        """End the row with a run of dashes reaching the edge of the panel."""
        fixed = sum(len(t) for t, _, f in self.parts if not f)
        self.parts.append(("—" * (PANEL_COLS - fixed - 1) + "-", None, False))
        return self

    def render(self, y: float) -> str:
        fixed = sum(len(t) for t, _, f in self.parts if not f)
        fills = sum(1 for _, _, f in self.parts if f)
        spare = PANEL_COLS - fixed
        if fills and spare < fills:
            raise ValueError(f"row too long by {fills - spare}: {self.plain()}")
        widths = [spare // fills + (1 if i < spare % fills else 0) for i in range(fills)] if fills else []
        out, n = [], 0
        for text, cls, is_fill in self.parts:
            if is_fill:
                text = "." * widths[n]
                n += 1
            text = escape(text)
            out.append(f'<tspan class="{cls}">{text}</tspan>' if cls else text)
        length = (fixed + sum(widths)) * PANEL_FONT * ADVANCE
        return (f'<text x="{PANEL_X}" y="{y:.1f}" textLength="{length:.1f}" '
                f'lengthAdjust="spacingAndGlyphs">{"".join(out)}</text>')

    def plain(self) -> str:
        return "".join(t for t, _, _ in self.parts)


def uptime(since: str, today: dt.date) -> str:
    start = dt.date.fromisoformat(since)
    months = (today.year - start.year) * 12 + today.month - start.month
    if today.day < start.day:
        months -= 1
    anchor_m = start.month - 1 + months
    anchor = start.replace(year=start.year + anchor_m // 12, month=anchor_m % 12 + 1)
    days = (today - anchor).days
    years, months = divmod(months, 12)

    def unit(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    return f"{unit(years, 'year')}, {unit(months, 'month')}, {unit(days, 'day')}"


def num(stats: dict, key: str) -> str:
    v = stats.get(key)
    return f"{v:,}" if isinstance(v, int) else "?"


def info_row(key: str, value: str) -> Row:
    return Row().add(". ", "dots").key(key).add(": ").fill().add(" ").add(value, "value")


def rule_row(label: str) -> Row:
    return Row().add(f"- {label} -").rule()


def stat_rows(stats: dict) -> list[Row]:
    return [
        Row().add(". ", "dots").key("Repos").add(": ").fill().add(" ")
             .add(num(stats, "repos"), "value").add(" {").key("Contributed").add(": ")
             .add(num(stats, "contributed"), "value").add("} | ").key("Stars").add(": ")
             .fill().add(" ").add(num(stats, "stars"), "value"),
        Row().add(". ", "dots").key("Commits").add(": ").fill().add(" ")
             .add(num(stats, "commits"), "value").add(" | ").key("Followers").add(": ")
             .fill().add(" ").add(num(stats, "followers"), "value"),
        Row().add(". ", "dots").key("Lines of Code").add(": ").fill().add(" ")
             .add(f'{stats["loc_add"] - stats["loc_del"]:,}' if "loc_add" in stats else "?", "value")
             .add(" ( ").add(num(stats, "loc_add") + "++", "add").add(", ")
             .add(num(stats, "loc_del") + "--", "del").add(" )"),
    ]


def panel_rows(profile: dict, stats: dict, today: dt.date) -> list[Row | None]:
    rows: list[Row | None] = [Row().add(profile["title"], "title").add(" -").rule()]
    for spec in profile["rows"]:
        if "rule" in spec:
            rows.append(rule_row(spec["rule"]))
        elif spec.get("stats"):
            rows += stat_rows(stats)
        elif "key" in spec:
            value = spec["value"].replace("$uptime", uptime(profile["github_since"], today))
            rows.append(info_row(spec["key"], value))
        else:
            rows.append(Row().add(".", "dots"))
    return rows


def build(theme: str, profile: dict, stats: dict, today: dt.date) -> str:
    c = PALETTES[theme]
    art = (ROOT / "assets" / f"ascii-{theme}.txt").read_text().rstrip("\n").split("\n")
    cols = max(len(line) for line in art)
    art_font = ART_WIDTH / (cols * ADVANCE)
    art_lh = art_font * ADVANCE * CELL_ASPECT

    rows = panel_rows(profile, stats, today)
    panel_h = (len(rows) + 1) * ROW_H          # +1 for the blinking prompt
    art_h = len(art) * art_lh
    height = round(max(panel_h, art_h) + 2 * MARGIN + 8)

    panel_y0 = (height - panel_h) / 2 + ROW_H * 0.78
    art_y0 = (height - art_h) / 2 + art_lh * 0.8

    out = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="ConsolasFallback,Consolas,Menlo,\'DejaVu Sans Mono\',monospace">',
        "<style>",
        "@font-face { font-family: 'ConsolasFallback'; src: local('Consolas'); size-adjust: 109%; }",
        f".key {{fill: {c['key']};}} .value {{fill: {c['value']};}} .dots {{fill: {c['dots']};}}",
        f".title {{fill: {c['key']}; font-weight: bold;}} .add {{fill: {c['add']};}} .del {{fill: {c['del']};}}",
        "text, tspan {white-space: pre;}",
        "</style>",
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="15" '
        f'fill="{c["bg"]}" stroke="{c["border"]}"/>',
        f'<g fill="{c["art"]}" font-size="{art_font:.2f}px" xml:space="preserve">',
    ]
    for i, line in enumerate(art):
        if line.strip():
            out.append(f'<text x="{MARGIN}" y="{art_y0 + i * art_lh:.2f}" '
                       f'textLength="{len(line) * art_font * ADVANCE:.2f}" '
                       f'lengthAdjust="spacingAndGlyphs">{escape(line)}</text>')
    out.append("</g>")
    out.append(f'<g fill="{c["fg"]}" font-size="{PANEL_FONT}px" xml:space="preserve">')
    for i, row in enumerate(rows):
        out.append(row.render(panel_y0 + i * ROW_H))
    prompt_y = panel_y0 + len(rows) * ROW_H
    out.append(
        f'<text x="{PANEL_X}" y="{prompt_y:.1f}"><tspan class="key">&gt; </tspan>'
        f'<tspan class="value">█<animate attributeName="opacity" values="1;0" dur="1.06s" '
        f'calcMode="discrete" repeatCount="indefinite"/></tspan></text>'
    )
    out += ["</g>", "</svg>", ""]
    return "\n".join(out)


def main() -> None:
    profile = json.loads((ROOT / "profile.json").read_text())
    try:
        stats = json.loads((ROOT / "cache" / "stats.json").read_text())
    except OSError:
        stats = {}
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).date()
    for theme in PALETTES:
        (ROOT / f"{theme}_mode.svg").write_text(build(theme, profile, stats, today))
    print("card built")


if __name__ == "__main__":
    main()
