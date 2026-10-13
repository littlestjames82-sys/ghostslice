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
from .ledger import summary as ledger_summary
from .pricing import estimate_cost, get_model, load_prices
from .profile import load_profile
from .scanner import scan
from .secrets_scan import scan_scan_result

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
    hist = ledger_summary(root)
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
<h2>Top files by estimated tokens</h2>
<table><tr><th>File</th><th>Tokens</th><th>Lines</th><th>Heat</th></tr>{''.join(rows)}</table>
<h2>Secrets</h2>
{sec_html}
<h2>Duplicates</h2>
<ul>{dup_html}</ul>
<h2>Prune recommendations</h2>
<table><tr><th>File</th><th>Tokens</th><th>Reason</th></tr>{rec_rows}</table>
<p>Recommendations to review, not instructions: dynamic imports and framework wiring can hide real use.</p>
<h2>Savings history</h2>
<p>{hist['runs']} recorded run(s); total saved {hist['total_saved_tokens']:,} estimated tokens
({hist['total_before_tokens']:,} &rarr; {hist['total_after_tokens']:,}).</p>
</body></html>
"""


def write_report(root, out, model_id: str = "claude-sonnet") -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(root, model_id=model_id), encoding="utf-8")
    return out
