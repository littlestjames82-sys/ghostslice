"""Self-contained offline HTML atlas.

One file, inline CSS + inline SVG, zero external assets, zero
network requests. Project data is embedded as JSON inside a
``<script type="application/json">`` block and read with
``JSON.parse`` + ``textContent`` rendering, following GhostSlice's
safe-rendering discipline (no project string is ever injected with
innerHTML). Heat toggles switch the JSON-driven node colours
between tokens, caller count, and git change activity.
"""
from __future__ import annotations

import html
import json
import math

from .brief import checked_box_lines
from .reading import dead_zones, reading_order

_CSS = """
body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:1100px;padding:0 1rem;color:#17141f}
h1{color:#6716f3} h2{margin-top:2rem;color:#2b2140}
table{border-collapse:collapse;width:100%} td,th{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.92rem}
.muted{color:#5c5470}.card{border:1px solid #e3ddf5;border-radius:10px;padding:1rem;margin:1rem 0}
button{margin-right:.4rem;padding:.35rem .8rem;border:1px solid #6716f3;background:#fff;border-radius:999px;cursor:pointer}
button.on{background:#6716f3;color:#fff}
svg{width:100%;height:auto;background:#fbfaff;border:1px solid #e3ddf5;border-radius:10px}
code{background:#f2eefc;padding:.1rem .3rem;border-radius:4px}
"""

_JS = """
const data = JSON.parse(document.getElementById('atlas-data').textContent);
let mode = 'tokens';
function esc(s){return String(s == null ? '' : s);}
function val(f){
  if(mode==='tokens') return f.tokens||0;
  if(mode==='callers') return f.importer_count||0;
  return (data.git.per_file||{})[f.path]||0;
}
function paint(){
  const vals = data.files.map(val); const max = Math.max(1, ...vals);
  document.querySelectorAll('[data-node]').forEach(function(el){
    const f = data.files[Number(el.getAttribute('data-node'))];
    const r = Math.sqrt(Math.max(0,val(f))/max);
    el.setAttribute('fill', 'rgba(103,22,243,' + (0.15 + 0.75*r).toFixed(2) + ')');
    const t = document.getElementById('tip');
  });
  document.querySelectorAll('[data-heat]').forEach(function(b){
    b.classList.toggle('on', b.getAttribute('data-heat')===mode);
  });
  const lbl = document.getElementById('heat-label');
  lbl.textContent = mode==='tokens' ? 'Heat: estimated tokens' :
    mode==='callers' ? 'Heat: caller count (files importing this file)' :
    'Heat: change activity (' + data.git.window + ', git log)';
}
document.querySelectorAll('[data-heat]').forEach(function(b){
  b.addEventListener('click', function(){ mode = b.getAttribute('data-heat'); paint(); });
});
let scale = 1;
document.getElementById('zin').addEventListener('click', function(){ scale = Math.min(3, scale*1.2); apply(); });
document.getElementById('zout').addEventListener('click', function(){ scale = Math.max(0.4, scale/1.2); apply(); });
function apply(){ document.getElementById('mapwrap').style.transform = 'scale(' + scale + ')'; }
paint();
"""


def _layout(data):
    """Deterministic column layout grouped by package. Returns
    (nodes, width, height) with node = file dict + x/y/r."""
    pkgs = {}
    for f in data.files:
        # Region = workspace package when one owns the file, else the
        # top-level directory (root files form the "(root)" region).
        region = f.get("package") or (
            f["path"].split("/", 1)[0] if "/" in f["path"] else "(root)")
        pkgs.setdefault(region, []).append(f)
    nodes = []
    col_w, row_h, x0, y = 190, 54, 20, 40
    width = x0 * 2
    for pi, pkg in enumerate(sorted(pkgs)):
        colx = x0 + pi * col_w
        width = max(width, colx + col_w)
        rows = sorted(pkgs[pkg], key=lambda f: (-f.get("tokens", 0), f["path"]))
        for ri, f in enumerate(rows):
            max_tok = max(1, max(g.get("tokens", 0) for g in data.files))
            r = 7 + 13 * math.sqrt(f.get("tokens", 0) / max_tok)
            nodes.append({**f, "x": colx + 24, "y": y + ri * row_h,
                          "r": round(r, 1), "pkg": pkg})
        y_max = y + len(rows) * row_h
    height = max(200, max((n["y"] for n in nodes), default=100) + 60)
    return nodes, width, height


def _svg(data, nodes, width, height):
    """Render the module map as inline SVG.

    Draws a package heading per column, one line per import-graph
    edge, and one circle per file (sized by the layout, coloured by
    the page's heat toggle). All project strings are HTML-escaped;
    a circle's ``<title>`` carries its path and estimated tokens.
    """
    idx = {f["path"]: i for i, f in enumerate(data.files)}
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="module map">']
    seen_pkg = set()
    for n in nodes:
        if n["pkg"] not in seen_pkg:
            seen_pkg.add(n["pkg"])
            parts.append(
                f'<text x="{n["x"] - 14}" y="22" font-size="12" '
                f'font-weight="bold" fill="#6716f3">{html.escape(n["pkg"])}</text>')
    for src, g in data.graph.items():
        for dst in g.get("imports", []):
            a = next((n for n in nodes if n["path"] == src), None)
            b = next((n for n in nodes if n["path"] == dst), None)
            if a and b:
                parts.append(
                    f'<line x1="{a["x"]}" y1="{a["y"]}" x2="{b["x"]}" y2="{b["y"]}" '
                    f'stroke="#b9a8e8" stroke-width="1"/>')
    last_pkg, last_x = None, 0
    for n in nodes:
        label = html.escape(n["path"].rsplit("/", 1)[-1])
        parts.append(
            f'<circle data-node="{idx[n["path"]]}" cx="{n["x"]}" cy="{n["y"]}" '
            f'r="{n["r"]}" fill="rgba(103,22,243,.4)">'
            f'<title>{html.escape(n["path"])}: {n.get("tokens", 0)} estimated tokens</title></circle>')
        parts.append(
            f'<text x="{n["x"] + n["r"] + 5}" y="{n["y"] + 4}" font-size="11">'
            f'{label}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_html(data, top_n: int = 10) -> str:
    """Render the complete, self-contained ``atlas.html`` document.

    The returned string is the whole artifact: inline CSS, inline
    SVG map, reading-order and package tables, dead zones, the
    checked / not-checked box, and the run data embedded as JSON
    for the local heat toggles. It references no external asset and
    makes no network request when opened. ``top_n`` caps the
    reading-order table, matching the brief from the same run.
    """
    order = reading_order(data, top_n)
    zones = dead_zones(data)
    nodes, width, height = _layout(data)
    payload = data.to_dict()
    payload["git"] = data.git
    payload_json = json.dumps(payload).replace("</", "<\\/")
    audience_note = (
        "Audience: diligence. This Atlas is an orientation aid, not an audit opinion."
        if data.audience == "diligence" else "Audience: onboarding.")
    parser_note = ("Import edges for Python come from the real import graph; other "
                   "languages are import-level and are parser-lite.")

    order_rows = "".join(
        f"<tr><td>{i+1}</td><td><code>{html.escape(o['path'])}</code></td>"
        f"<td>{html.escape(o['reason'])}</td><td>{o['tokens']}</td>"
        f"<td>{o['reading_minutes']}</td></tr>"
        for i, o in enumerate(order)) or '<tr><td colspan="5">No reading order could be derived.</td></tr>'
    pkg_rows = "".join(
        f"<tr><td><code>{html.escape(p.get('label') or p.get('path') or '(root)')}</code></td>"
        f"<td>{p.get('files', 0)}</td><td>{p.get('tokens', 0)}</td></tr>"
        for p in data.packages)
    collapsed = [f for f in data.files if f.get("is_generated") or f.get("is_vendored")]
    collapsed_txt = (", ".join(html.escape(f["path"]) for f in collapsed)
                     if collapsed else "None flagged.")
    dead_rows = "".join(
        f"<li><code>{html.escape(d['path'])}</code>: {html.escape(d.get('reason', ''))}</li>"
        for d in zones["dead_files"][:20]) or "<li>None found by static analysis.</li>"
    cov = getattr(data, "test_coverage", None) or {}
    cov_sources = cov.get("sources") or []
    if cov_sources:
        cov_summary = cov.get("summary", {})

        def _linked_from(src):
            if src["status"] == "direct":
                return ", ".join(html.escape(t) for t in src.get("test_files", []))
            if src["status"] == "indirect":
                root = src.get("direct_source") or src.get("via") or ""
                return f"via {html.escape(root)} (import graph)"
            return "no test link found"

        cov_rows = "".join(
            f"<tr><td><code>{html.escape(src['path'])}</code></td>"
            f"<td>{html.escape(src['status'])}</td>"
            f"<td>{_linked_from(src)}</td></tr>"
            for src in cov_sources)
        test_section = (
            "<h2>Test layout</h2>"
            "<p>Static test linkage only: tests were not executed, so this "
            "is not measured coverage. Directly linked means a test file "
            "imports the source file or follows its test naming "
            "convention; indirectly linked means reachable from a "
            "directly linked file through the import graph.</p>"
            f"<p>Source files: {cov_summary.get('source_files', len(cov_sources))}: "
            f"{cov_summary.get('direct', 0)} directly linked, "
            f"{cov_summary.get('indirect', 0)} indirectly linked, "
            f"{cov_summary.get('unlinked', 0)} with no test link found.</p>"
            "<table><tr><th>Source file</th><th>Test linkage</th>"
            f"<th>Linked from</th></tr>{cov_rows}</table>")
    else:
        test_section = (
            "<h2>Test layout</h2>"
            "<p>No code source files were found for static test linkage.</p>")
    checked = "".join(f"<li>{html.escape(ln)}</li>" for ln in checked_box_lines(data))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>GhostAtlas: {html.escape(data.title)}</title>
<style>{_CSS}</style></head><body>
<h1>GhostAtlas: {html.escape(data.title)}</h1>
<p class="muted">Generated {html.escape(data.generated_at)} | Engine: {html.escape(data.engine)} | {html.escape(audience_note)}</p>
<p>Files: {len(data.files)} | Total estimated tokens: {data.total_tokens} | Total size: {data.total_size} bytes. Token counts are estimates from the GhostSlice estimator, not exact tokenizer counts.</p>
<p class="muted">{html.escape(parser_note)}</p>
<h2>Module map</h2>
<p>Packages/workspaces are laid out as columns by package path. Nodes are sized by estimated tokens. Generated/vendored files collapsed in reading surfaces and labelled here: {collapsed_txt}</p>
<p><button data-heat="tokens" class="on">Tokens</button><button data-heat="callers">Callers</button><button data-heat="activity">Change activity</button>
<button id="zin" type="button">Zoom in</button><button id="zout" type="button">Zoom out</button></p>
<p id="heat-label" class="muted"></p>
<div style="overflow:auto"><div id="mapwrap" style="transform-origin:top left">{_svg(data, nodes, width, height)}</div></div>
<h2>Start here: reading order</h2>
<table><tr><th>#</th><th>File</th><th>Why (factual reason)</th><th>Est. tokens</th><th>Est. minutes</th></tr>{order_rows}</table>
<h2>Packages</h2>
<table><tr><th>Package</th><th>Files</th><th>Est. tokens</th></tr>{pkg_rows}</table>
{test_section}
<h2>Dead zones: worth asking about</h2>
<p>Observations from static analysis for a human to judge, not delete instructions.</p>
<ul>{dead_rows}</ul>
<h2>Checked / not checked</h2>
<ul>{checked}</ul>
<script type="application/json" id="atlas-data">{payload_json}</script>
<script>{_JS}</script>
</body></html>
"""
