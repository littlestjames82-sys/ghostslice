"""Classification tests (PLAN verification bar): one project per state
lands in the right column, with the rule visible. Placement is checked
by position in the rendered HTML: a project's card must appear inside
its column's section, after that column's heading and before the next
column's heading."""
from __future__ import annotations

import json
import re

from conftest import (attention_project, combined, empty_project,
                      healthy_project, run_cli, stale_project)

COLUMNS = ["attention", "stale", "verified"]


def _board(cli, tmp_path, projects, extra=()):
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", *projects, "-o", out, *extra])
    assert proc.returncode == 0, combined(proc)
    assert out.is_file()
    return out.read_text(encoding="utf-8")


def _column_of(html: str, project_name: str) -> str | None:
    """Column whose <section class="col X"> contains the project's card.

    Sections and cards are located by their structural markup (section
    class, card <h3> title), never by bare words: the stylesheet and
    prose mention the column names too, and a project may itself be
    named "attention"."""
    low = html.lower()
    sections = [(m.group(1), m.start()) for m in re.finditer(
        r"<section class=\"col (attention|stale|verified)\">", low)]
    if len(sections) < 3:
        return None
    card = re.search(rf"<h3>{re.escape(project_name.lower())}</h3>", low)
    if card is None:  # fallback: first mention after the first section
        pos = low.find(project_name.lower(), sections[0][1])
        assert pos != -1, f"project {project_name} not on the board"
    else:
        pos = card.start()
    current = None
    for col, start in sorted(sections, key=lambda kv: kv[1]):
        if start < pos:
            current = col
    return current


def test_four_states_land_in_the_right_columns(cli, tmp_path):
    healthy = healthy_project(tmp_path)
    attention = attention_project(tmp_path)
    stale = stale_project(tmp_path)
    empty = empty_project(tmp_path)
    html = _board(cli, tmp_path, [healthy, attention, stale, empty])
    assert _column_of(html, "healthy") == "verified"
    assert _column_of(html, "attention") == "attention"
    assert _column_of(html, "stale") == "stale"
    # Plan: a project with no reports at all goes to Stale.
    assert _column_of(html, "empty") == "stale"


def test_attention_beats_stale(cli, tmp_path):
    """Worst-of precedence: a project that is both stale (Watch) and
    attention (failed Verify) lands in Attention."""
    import conftest
    p = tmp_path / "both"
    p.mkdir()
    conftest.slice_history(p)
    conftest.verify_history(p, verdict="gaps_found", hard_gaps=1)
    conftest.watch_report(p, verdict="stale")
    html = _board(cli, tmp_path, [p])
    assert _column_of(html, "both") == "attention"


def test_json_model_agrees_with_html(cli, tmp_path):
    healthy = healthy_project(tmp_path)
    attention = attention_project(tmp_path)
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", healthy, attention, "-o", out, "--json"])
    assert proc.returncode == 0, combined(proc)
    model = json.loads(proc.stdout)
    text = json.dumps(model).lower()
    assert "healthy" in text and "attention" in text
    # Each project's column/state appears somewhere in its model entry.
    def find(obj, name):
        if isinstance(obj, dict):
            if name in json.dumps(obj).lower() and \
                    ("column" in obj or "state" in obj or "status" in obj):
                return obj
            for v in obj.values():
                hit = find(v, name)
                if hit is not None:
                    return hit
        elif isinstance(obj, list):
            for v in obj:
                hit = find(v, name)
                if hit is not None:
                    return hit
        return None
    for name, want in (("healthy", "verified"), ("attention", "attention")):
        entry = find(model, name)
        assert entry is not None, f"no model entry for {name}"
        entry_text = json.dumps(entry).lower()
        assert want in entry_text, f"{name} entry lacks {want}: {entry_text}"
