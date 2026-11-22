"""Dashboard panel fragment (for embedding in GhostSlice's dashboard):
memory heat list, pinned rules first, include/exclude state, combined
total. All item text is HTML-escaped; no item content is injected raw.
"""
from __future__ import annotations
import html

from .tokens import estimate

def render_panel(selected, not_selected, total_tokens: int = 0) -> str:
    """Render the dashboard panel HTML fragment for a selection.

    *selected* and *not_selected* are the lists returned by
    recall.select(); *total_tokens* is the combined estimated total
    shown in the header. All item text is HTML-escaped.
    """
    rows = []
    for e in selected:
        it = e["item"]
        pin_cls = " gr-pinned" if e["pinned"] else ""
        pin_txt = " · pinned rule" if e["pinned"] else ""
        rows.append(
            '<li class="gr-item' + pin_cls + '">'
            f'<span class="gr-title">{html.escape(it.title)}</span> '
            f'<span class="gr-meta">{html.escape(it.source_type)} · '
            f'{html.escape(it.provenance.path)} · {estimate(it.text)} est. tokens'
            f'{pin_txt} · included</span></li>')
    for e in not_selected:
        it = e["item"]
        rows.append(
            f'<li class="gr-item gr-excluded"><span class="gr-title">{html.escape(it.title)}</span> '
            f'<span class="gr-meta">{html.escape(it.provenance.path)} · excluded: '
            f'{html.escape(str(e["reason"]))}</span></li>')
    return ('<section id="ghostrecall-panel"><h2>GhostRecall: project memory</h2>'
            f'<p>Combined memory total: {total_tokens} estimated tokens</p>'
            f'<ul>{"".join(rows)}</ul></section>')
