"""Corpus report: single-file offline HTML, plain words first, appendix second.

Held-out documents are named by path + finding type only, never values.
Sensitive-held documents appear in the held-out section, and not in any
export described here.
"""
from __future__ import annotations

import html
from pathlib import Path

from .scan import Corpus


def render_report(corpus: Corpus) -> str:
    """Render the corpus report as one self-contained HTML string.

    No external assets are referenced, so the file works offline.
    Held-out documents are named by path and finding type only.
    """
    s = corpus.summary()
    total = corpus.total_tokens or 1
    rows = []
    for d in sorted(corpus.docs, key=lambda d: -d.tokens):
        bar = max(1, round(120 * d.tokens / total))
        flags = ", ".join(d.extraction.flags) or "-"
        rows.append(
            f"<tr><td>{html.escape(d.path)}</td><td>{d.tokens}</td>"
            f"<td><div class='bar' style='width:{bar}px'></div></td>"
            f"<td>{html.escape(d.date or '-')} ({html.escape(d.date_source)})</td>"
            f"<td>{html.escape(flags)}</td><td>{'held out' if d.held_out else ''}</td></tr>")
    cluster_rows = []
    for c in corpus.clusters:
        cluster_rows.append(
            f"<tr><td>{html.escape(', '.join(c.members))}</td><td>{c.kind}</td>"
            f"<td>{html.escape(c.probable_current)}<br><small>{html.escape(c.current_reason)}</small></td>"
            f"<td>{html.escape(', '.join(c.stale) or '-')}</td><td>{c.wasted_tokens}</td></tr>")
    not_cov = "".join(
        f"<li>{html.escape(n.path)} - {html.escape(n.reason)}</li>"
        for n in corpus.not_covered) or "<li>None</li>"
    held = []
    for d in corpus.docs:
        if d.held_out:
            types = sorted({f.type for f in d.findings})
            held.append(f"<li>{html.escape(d.path)} - {html.escape(', '.join(types))} "
                        f"(path and type only, values never shown)</li>")
    stale_all = sorted({p for c in corpus.clusters for p in c.stale})
    stale_list = "".join(f"<li>{html.escape(p)}</li>" for p in stale_all) or "<li>None</li>"
    saving = corpus.total_tokens - (corpus.total_tokens - corpus.wasted_tokens)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>GhostDocs corpus report</title>
<style>body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem}}
.bar{{background:#6716f3;height:10px;display:inline-block}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top}}small{{color:#666}}</style>
</head><body>
<h1>Your documents, ready for an agent</h1>
<p>This report shows what is in this document set, what it would cost an agent to read,
where the same information is repeated, and what was left out. Token numbers are estimates.</p>
<ul>
<li>Documents read: {s['documents']}</li>
<li>Total size if sent as-is: about {s['total_estimated_tokens']} tokens</li>
<li>Repeated material: about {s['wasted_estimated_tokens']} tokens across {s['duplicate_clusters']} duplicate groups</li>
<li>Size after removing repeats: about {s['deduped_estimated_tokens']} tokens (saving about {saving} tokens)</li>
<li>Documents held back for sensitive content: {s['held_out_documents']}</li>
<li>Files GhostDocs could not read: {s['coverage_gaps']}</li>
</ul>
<h2>Biggest documents first</h2>
<table><tr><th>Document</th><th>Est. tokens</th><th></th><th>Date</th><th>Extraction flags</th><th></th></tr>
{''.join(rows)}</table>
<h2>Duplicates and older versions</h2>
<p>The probable current version is a heuristic (newest dated, unless an authoritative folder is set in the profile). Check it before relying on it.</p>
<table><tr><th>Group</th><th>Kind</th><th>Probable current</th><th>Older (stale)</th><th>Wasted tokens</th></tr>
{''.join(cluster_rows) or '<tr><td colspan="5">No duplicates found</td></tr>'}</table>
<h2>Older versions (stale list)</h2><ul>{stale_list}</ul>
<h2>Held out of exports (sensitive shapes found)</h2>
<ul>{''.join(held) or '<li>None</li>'}</ul>
<h2>Could not be read</h2><ul>{not_cov}</ul>
<h2>Technical appendix</h2>
<p>Estimator: character-based estimate, labelled estimate everywhere. Chunk boundaries in exports are
document sections. Formats covered in v0.1: Markdown, plain text, HTML, PDF text layer only.
DOCX and image-only PDFs are listed as not covered, never silently skipped. No OCR, no model calls,
no network. Probable-current duplicate choices follow the profile's authoritative sources first,
then newest date, and that ordering is a heuristic, not a fact.</p>
</body></html>
"""


def write_report(corpus: Corpus, out: Path) -> Path:
    """Write :func:`render_report` to *out* and return the path written."""
    out = Path(out)
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(corpus), encoding="utf-8")
    return out
