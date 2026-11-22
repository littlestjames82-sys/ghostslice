"""Renderers: HTML board, plain text summary, JSON model.

HTML safety rule: every string that came from a file (or from a path,
or from a verdict) passes through html.escape at render time. There
is no raw-HTML path in this module. The template itself contains no
JavaScript and no external reference of any kind.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from .model import COLUMNS, LEVEL_PLAIN, VERIFICATION_LEVELS, ProjectBoard

# One plain-words line explaining the evidence levels, printed on
# every board so a reader who never saw the evidence contract still
# knows what a row's level means. A level is shown on a row only
# when the report itself states one; unstated is never upgraded.
LEVEL_LEGEND = (
    "Verification levels: "
    + "; ".join(f"{level} = {LEVEL_PLAIN[level]}"
                for level in VERIFICATION_LEVELS[1:])
    + ". A level appears on a row only when the report states one; "
    "no stated level means the report did not say, not that the "
    "check was weaker or stronger."
)

COLUMN_TITLES = {
    "verified": "Verified",
    "attention": "Attention",
    "stale": "Stale",
}

STATE_LABELS = {
    "ok": "ok",
    "attention": "attention",
    "stale": "stale",
    "absent": "no report",
    "unreadable": "unreadable",
}

CSS = """
body { font-family: system-ui, sans-serif; margin: 2rem; background: #111; color: #eee; }
header h1 { margin-bottom: 0.2rem; }
header p, footer p { color: #aaa; }
.board { display: flex; gap: 1rem; align-items: flex-start; flex-wrap: wrap; }
.col { flex: 1 1 300px; background: #1b1b1b; border-radius: 8px; padding: 1rem; }
.col h2 { margin-top: 0; }
.col.verified h2 { color: #7dc47f; }
.col.attention h2 { color: #e08a8a; }
.col.stale h2 { color: #d8b25c; }
.card { background: #242424; border-radius: 6px; padding: 0.8rem; margin-bottom: 1rem; }
.card h3 { margin: 0 0 0.2rem 0; }
.card .path, .card .why { color: #999; font-size: 0.85em; }
.card ul { list-style: none; padding: 0; margin: 0.6rem 0 0 0; }
.card li { padding: 0.25rem 0; border-top: 1px solid #333; font-size: 0.92em; }
.chip { display: inline-block; min-width: 5.2em; text-align: center; border-radius: 4px; padding: 0 0.3em; margin-right: 0.5em; font-size: 0.82em; background: #444; }
.chip.ok { background: #2e5d31; }
.chip.attention, .chip.unreadable { background: #6e2f2f; }
.chip.stale { background: #6e5a24; }
.chip.absent { background: #333; color: #999; }
.meta { color: #999; font-size: 0.85em; }
""".strip()


def esc(value) -> str:
    """HTML-escape any value for the board (quotes included)."""
    return html.escape(str(value), quote=True)


def age_text(when: datetime | None, now: datetime) -> str:
    """Short relative age such as ``"5m ago"``; ``""`` when unknown."""

    if when is None:
        return ""
    delta = now - when
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "in the future"
    if seconds < 3600:
        return f"{max(seconds // 60, 0)}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def render_html(model: dict) -> str:
    """Render the model as one self-contained, script-free HTML file."""
    boards: list[ProjectBoard] = model["boards"]
    now = datetime.fromisoformat(model["generated_at"])
    by_column = {c: [b for b in boards if b.column == c] for c in COLUMNS}
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>GhostConsole board</title>",
        "<style>",
        CSS,
        "</style>",
        "</head>",
        "<body>",
        "<header>",
        "<h1>GhostConsole board</h1>",
        f"<p>Generated {esc(model['generated_at'])} from local report "
        f"files only. {len(boards)} project(s). Stale window: "
        f"{esc(model['stale_days'])} day(s). Read-only: this board was "
        "built by reading reports, no tool was run.</p>",
        f"<p>{esc(LEVEL_LEGEND)}</p>",
        "</header>",
        '<main class="board">',
    ]
    for column in COLUMNS:
        parts.append(f'<section class="col {column}">')
        parts.append(f"<h2>{COLUMN_TITLES[column]} "
                     f"({len(by_column[column])})</h2>")
        for board in by_column[column]:
            parts.append('<article class="card">')
            parts.append(f"<h3>{esc(board.name)}</h3>")
            parts.append(f'<div class="path">{esc(board.path)}</div>')
            parts.append(f'<div class="why">Why here: '
                         f"{esc(board.column_reason)}</div>")
            parts.append("<ul>")
            for section in board.sections:
                label = STATE_LABELS.get(section.state, section.state)
                meta_bits = []
                if section.when is not None:
                    kind = f" ({section.time_kind})" if section.time_kind \
                        else ""
                    meta_bits.append(age_text(section.when, now) + kind)
                if section.verification_level:
                    meta_bits.append(
                        f"level: {section.verification_level}")
                if section.source:
                    meta_bits.append(section.source)
                meta = " · ".join(meta_bits)
                trend = (f' <span class="meta">trend: '
                         f"{esc(section.trend)}</span>"
                         if section.trend else "")
                parts.append(
                    f'<li><span class="chip {esc(section.state)}">'
                    f"{esc(label)}</span><strong>{esc(section.tool)}"
                    f"</strong>: {esc(section.summary)}"
                    + (f' <span class="meta">{esc(meta)}</span>'
                       if meta else "")
                    + trend
                    + "</li>")
            parts.append("</ul>")
            parts.append("</article>")
        parts.append("</section>")
    parts += [
        "</main>",
        "<footer>",
        "<p>A card in Verified means the latest reports on disk say ok. "
        "It is a statement about saved reports, not a live guarantee "
        "about the project. Absent rows mean the tool has not reported "
        "for that project, or its report was not found in the bounded "
        "search.</p>",
        "</footer>",
        "</body>",
        "</html>",
    ]
    return "\n".join(parts) + "\n"


def render_text(model: dict) -> str:
    """Render the model as a plain-text summary, grouped by column."""
    boards: list[ProjectBoard] = model["boards"]
    now = datetime.fromisoformat(model["generated_at"])
    lines = [
        f"GhostConsole summary - generated {model['generated_at']} "
        f"(stale window {model['stale_days']} day(s))",
        LEVEL_LEGEND,
    ]
    for column in COLUMNS:
        group = [b for b in boards if b.column == column]
        lines.append("")
        lines.append(f"{COLUMN_TITLES[column].upper()} ({len(group)})")
        for board in group:
            lines.append(f"  {board.name} - {board.column_reason}")
            lines.append(f"    {board.path}")
            for section in board.sections:
                label = STATE_LABELS.get(section.state, section.state)
                age = age_text(section.when, now)
                age = f" ({age})" if age else ""
                level = (f" | level: {section.verification_level}"
                         if section.verification_level else "")
                trend = f" | trend: {section.trend}" if section.trend \
                    else ""
                lines.append(f"    [{label}] {section.tool}: "
                             f"{section.summary}{age}{level}{trend}")
    return "\n".join(lines) + "\n"


def render_json(model: dict) -> str:
    """Render the model as indented JSON (projects, not board objects)."""
    payload = {
        "generated_at": model["generated_at"],
        "stale_days": model["stale_days"],
        "projects": model["projects"],
    }
    return json.dumps(payload, indent=2) + "\n"
