# Dashboard

Part of the [GhostSlice README](../README.md). The local visual context tree.

## Dashboard: visual context tree

```bash
ghostslice serve ~/my-project --port 8765
# open http://127.0.0.1:8765/
```

A single-page local UI (served by the Python process, bound to 127.0.0.1):
files sorted by token cost with a heat bar, click a row to include/exclude
it, a per-file mode selector, live before/after totals, a model selector
with pre-flight dollar cost, a slice preview pane, and an Export button
that writes a `.claude_context` bundle inside the served project. A
Treemap toggle (v0.5) swaps the list for a squarified treemap: nested
rectangles grouped by top-level directory, sized by estimated tokens
and coloured by the same heat palette; clicking a rectangle toggles
include/exclude just like the list. The list stays the default view.

Dashboard v2 (v0.22): clicking a file opens a **side-by-side slice
preview** — the original text on the left, its slice on the right, with
the original → sliced estimated tokens and % saved in the header and a
mode switcher that re-slices live (`GET /api/slice`). Each side's text
is capped at 200,000 characters (the response flags `truncated`; token
counts always describe the full file). The endpoint only serves files
in the scan, and only when the file's resolved path stays inside the
project root — `..` segments, absolute paths, and symlinks pointing
outside are refused, and file content reaches the page as inert text
(`textContent`, never markup).

A **What-if panel** (`POST /api/whatif`) previews export options — a
global mode override, a budget/fit target (slider + number), and
exclude-secrets / redact / auto-shrink toggles — and reports the
would-be totals, the delta against a plain default export, how many
files change mode, and whether the budget fits. It writes nothing and
records no history: the totals are computed in memory with the
exporter's own mode resolution, fit ladder, slicer, and redactor, in
the exporter's order, so they are exactly what a real export with the
same options reports (test-pinned against `build_bundle`, including
fit + redact, where the totals are post-redaction). The Export button
sends the same panel options, so what you previewed is what you
export. Two consistency fixes ride along: the dashboard export now
honours the project's `.ghostslice.json` profile (its own scan
already did), and the export `out` path is verified to stay inside
the served project. The dashboard is a startup snapshot: the file
set, secret findings, and token table reflect the project as scanned
when `serve` started.

Call graph panel (v1.0.2): selecting a file also lists its Python
symbols with **who calls each one and what each one calls** (plus a
"possibly dead" tag for symbols nothing reaches). The data rides
the existing `GET /api/graph` response as a `"calls"` payload —
symbols in full, call edges capped at 2,000 and dead candidates at
200, with the true totals and truncation flags reported when a cap
engages. It is kept for the server run; since v1.0.3 `serve`
starts building it on a background thread at startup, so the
first request usually finds it ready instead of paying the
build (a request that beats the build simply waits for the same
payload). Call analysis covers Python files only; other files
honestly show "no call data" in the panel.

Per-symbol call lists (v1.0.6): the bulk payload's 2,000-edge cap
hides most relationships on a large project, so the panel can
fetch one symbol's complete lists from `GET /api/calls?symbol=`
(a symbol id like `util.py:helper`, or a qualified name — one
matching symbols in several files is answered with the candidate
list, never a silent pick; an unknown symbol is a 404). The
endpoint serves the same memoised call graph as `/api/graph` (no
second build; a request during the startup warm-up waits for the
same build), returning the symbol's callers, callees, and
referenced-by with per-list caps of 500, true totals, and
truncation flags. When the bulk payload is truncated, each symbol
in the panel grows a "complete lists" button that swaps its lists
for the fetched ones and says whether they are complete or were
themselves capped.
