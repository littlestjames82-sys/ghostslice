"""Standalone HTML report (v0.4).

Single self-contained file: inline CSS, violet accent #6716f3 (matching
the dashboard), no external assets, no JavaScript required to read it.
All project-derived strings are HTML-escaped.
"""
from __future__ import annotations

import html
from pathlib import Path

from .duplicates import find_duplicates
from .exporter import estimate_context_tokens
from .graph import build_graph, recommendations
from .ledger import analytics as ledger_analytics
from .pricing import estimate_cost, get_model, load_prices
from .profile import load_profile
from .scanner import scan
from .secrets_scan import scan_scan_result
from .workspaces import summarize_packages

_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem auto;max-width:960px;padding:0 1rem;color:#1c1b22}
h1{color:#6716f3} h2{margin-top:2rem;border-bottom:2px solid #6716f3;padding-bottom:.25rem}
table{border-collapse:collapse;width:100%} td,th{padding:.3rem .5rem;border-bottom:1px solid #ddd;text-align:left}
.bar{background:#eee;height:10px;border-radius:3px;min-width:120px}.fill{background:#6716f3;height:10px;border-radius:3px}
.warn{background:#fff3f3;border:1px solid #e0a3a3;padding:.75rem 1rem;border-radius:6px}
.ok{background:#f3f0ff;border:1px solid #c9b8ff;padding:.75rem 1rem;border-radius:6px}
code{background:#f5f2ff;padding:.1rem .3rem;border-radius:3px}
"""


def _e(x) -> str:
    return html.escape(str(x), quote=True)


def _history_svg(runs: list[dict]) -> str:
    """Inline SVG chart of ledger runs: violet bars = saved tokens
    per run (zero line drawn when a run saved negative), dark polyline
    = after tokens on its own min/max scale (labelled as such). Pure
    SVG: no JS, no external assets. Only numbers and ledger timestamps
    are rendered, and the timestamps are escaped."""
    width, height = 880, 200
    top, bottom_pad, side = 20, 24, 8
    plot_w = width - 2 * side
    plot_h = height - top - bottom_pad
    base_y = top + plot_h
    saved = [r["saved_tokens"] for r in runs]
    after = [r["after_tokens"] for r in runs]
    smax = max(saved + [0])
    smin = min(saved + [0])
    srange = (smax - smin) or 1
    zero_y = top + plot_h * (smax / srange)
    slot = plot_w / len(runs)
    bar_w = max(1.0, slot * 0.62)
    parts = [
        f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
        f"role='img' aria-label='Savings history chart' "
        f"style='max-width:100%;background:#faf9ff;border:1px solid #ddd;border-radius:6px'>",
        f"<line x1='{side}' y1='{zero_y:.1f}' x2='{width - side}' y2='{zero_y:.1f}' "
        "stroke='#bbb' stroke-width='1'/>",
    ]
    for i, v in enumerate(saved):
        cx = side + slot * i + slot / 2
        h = abs(v) / srange * plot_h
        y = zero_y - h if v >= 0 else zero_y
        parts.append(
            f"<rect x='{cx - bar_w / 2:.1f}' y='{y:.1f}' width='{bar_w:.1f}' "
            f"height='{h:.1f}' fill='#6716f3' opacity='0.85'>"
            f"<title>run {i + 1}: saved {v:,} estimated tokens</title></rect>")
    amin, amax = min(after), max(after)
    arange = (amax - amin) or 1
    pts = []
    for i, v in enumerate(after):
        cx = side + slot * i + slot / 2
        cy = top + plot_h * (1 - (v - amin) / arange)
        pts.append(f"{cx:.1f},{cy:.1f}")
    parts.append(
        f"<polyline points='{' '.join(pts)}' fill='none' stroke='#1c1b22' "
        "stroke-width='2'/>")
    for p in pts:
        x, y = p.split(",")
        parts.append(f"<circle cx='{x}' cy='{y}' r='2.5' fill='#1c1b22'/>")
    first_at = _e((runs[0].get("at") or "?")[:10])
    last_at = _e((runs[-1].get("at") or "?")[:10])
    parts.append(
        f"<text x='{side}' y='13' font-size='11' fill='#555'>saved per run: "
        f"max {smax:,}</text>")
    parts.append(
        f"<text x='{width - side}' y='13' font-size='11' fill='#555' "
        f"text-anchor='end'>after tokens (own scale): {amin:,}–{amax:,}</text>")
    parts.append(
        f"<text x='{side}' y='{height - 6}' font-size='11' fill='#555'>"
        f"{first_at}</text>")
    parts.append(
        f"<text x='{width - side}' y='{height - 6}' font-size='11' fill='#555' "
        f"text-anchor='end'>{last_at}</text>")
    parts.append("</svg>")
    return "".join(parts)


def build_report(root, model_id: str = "claude-sonnet") -> str:
    profile = load_profile(root)
    matcher = profile.is_ignored if profile.path else None
    result = scan(root, ignore_matcher=matcher)
    graph = build_graph(result)
    recs = recommendations(result, graph, profile)
    dups = find_duplicates(result)
    secrets = scan_scan_result(result)
    prices = load_prices()
    try:
        model = get_model(prices, model_id or profile.model or "claude-sonnet")
    except KeyError:
        model = get_model(prices, "claude-sonnet")
    before, after = estimate_context_tokens(root, profile=profile)
    cost_after = estimate_cost(after, model)
    hist = ledger_analytics(root, model=model, prices=prices)
    if hist["runs"]:
        hist_warn = ""
        if hist["estimator"]["warning"]:
            hist_warn = (f"<div class='warn'>{_e(hist['estimator']['warning'])}</div>")
        if hist["corrupt_lines"]:
            hist_warn += (f"<p>Skipped {hist['corrupt_lines']} corrupt ledger "
                          "line(s); they are not counted below.</p>")
        agg = hist["aggregates"]
        history_html = (
            "<h2>Savings history</h2>\n"
            f"<p>{hist['runs']} recorded run(s); total saved "
            f"{hist['total_saved_tokens']:,} estimated tokens "
            f"({hist['total_before_tokens']:,} &rarr; "
            f"{hist['total_after_tokens']:,}).</p>\n"
            f"{hist_warn}"
            f"{_history_svg(hist['runs_detail'])}\n"
            f"<p>Bars: saved estimated tokens per run. Line: after tokens "
            f"per run (own scale). Total estimated $ saved at "
            f"{_e(model.get('name', model['id']))}: "
            f"~${agg.get('total_saved_cost_usd', 0.0):.4f} "
            f"(prices as of {_e(prices.get('as_of'))}, local snapshot, "
            "not live; input rates).</p>")
    else:
        history_html = ""
    # v0.13: per-package subtotals, shown only for real monorepos.
    packages = summarize_packages(result)
    if len(packages) > 1:
        pkg_rows = "".join(
            f"<tr><td>{_e(p['label'])}</td><td>{_e(p['kind'])}</td>"
            f"<td>{_e(p['source'])}</td><td>{p['files']:,}</td>"
            f"<td>{p['tokens']:,}</td><td>{p['share']:.1f}%</td></tr>"
            for p in packages)
        packages_html = (
            "<h2>Packages</h2>\n"
            "<table><tr><th>Package</th><th>Kind</th><th>Source</th>"
            f"<th>Files</th><th>Tokens</th><th>Share</th></tr>{pkg_rows}</table>\n"
            "<p>Kinds: <em>declared</em> = named by a workspace manifest "
            "(npm/pnpm/Cargo/go.work/uv); <em>detected</em> = fallback, a "
            "top-level directory carrying its own manifest; the root "
            "package is labelled (root). Shares are of original estimated "
            "tokens.</p>")
    else:
        packages_html = ""
    max_tokens = max((f.tokens for f in result.files), default=1) or 1

    rows = []
    for f in result.files[:50]:
        pct = max(1, round(100 * f.tokens / max_tokens))
        rows.append(
            f"<tr><td>{_e(f.path)}</td><td>{f.tokens:,}</td><td>{f.lines:,}</td>"
            f"<td><div class='bar'><div class='fill' style='width:{pct}%'></div></div></td></tr>")
    rec_rows = "".join(
        f"<tr><td>{_e(r['path'])}</td><td>{r['tokens']:,}</td><td>{_e(r['reason'])}</td></tr>"
        for r in recs) or "<tr><td colspan='3'>None</td></tr>"
    dup_lines = []
    for g in dups["exact"]:
        dup_lines.append(f"<li>Exact duplicate: {_e(', '.join(g['files']))} "
                         f"(potential saving {g['potential_savings']:,} estimated tokens)</li>")
    for pair in dups["near"]:
        dup_lines.append(f"<li>Near-duplicate ({pair['similarity']}): {' &harr; '.join(_e(p) for p in pair['files'])}</li>")
    dup_html = "".join(dup_lines) or "<li>None found</li>"
    if secrets:
        sec_items = "".join(
            f"<li>{_e(s['path'])}:{s['line']} &mdash; {_e(s['type'])} ({_e(s['redacted'])})</li>"
            for s in secrets)
        sec_html = f"<div class='warn'><strong>{len(secrets)} possible secret(s) found (redacted):</strong><ul>{sec_items}</ul></div>"
    else:
        sec_html = "<div class='ok'>No likely secrets found in scanned files.</div>"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>GhostSlice Report &mdash; {_e(result.root)}</title><style>{_CSS}</style></head>
<body>
<h1>GhostSlice Report</h1>
<p>Project: <code>{_e(result.root)}</code></p>
<p>Token counts are <strong>estimates</strong> (BPE-like split v2, per-language calibrated, not exact tokenizer counts).
Prices are a local, dated snapshot (as of {_e(prices.get('as_of'))}), not live.</p>
<h2>Totals</h2>
<ul>
<li>Files: {len(result.files):,}</li>
<li>Total estimated tokens (full): {result.total_tokens:,}</li>
<li>Sliced selection: {before:,} &rarr; {after:,} estimated tokens (saved {before-after:,})</li>
<li>Pre-flight input cost at {_e(model.get('name', model['id']))}: ~${cost_after:.4f} for the sliced selection</li>
</ul>
{packages_html}
<h2>Top files by estimated tokens</h2>
<table><tr><th>File</th><th>Tokens</th><th>Lines</th><th>Heat</th></tr>{''.join(rows)}</table>
<h2>Secrets</h2>
{sec_html}
<h2>Duplicates</h2>
<ul>{dup_html}</ul>
<h2>Prune recommendations</h2>
<table><tr><th>File</th><th>Tokens</th><th>Reason</th></tr>{rec_rows}</table>
<p>Recommendations to review, not instructions: dynamic imports and framework wiring can hide real use.</p>
{history_html}
</body></html>
"""


def write_report(root, out, model_id: str = "claude-sonnet") -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(root, model_id=model_id), encoding="utf-8")
    return out
