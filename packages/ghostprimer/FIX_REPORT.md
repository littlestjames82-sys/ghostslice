# GhostPrimer v0.1 - Fix report (D1-D3 from REPORT_B.md)

## Result

```
PYTHONPATH=src python3 -m pytest tests -q
Baseline: 28 passed, 3 failed  (reproduced before editing)
After:    31 passed, 0 failed
```

No tests were edited or weakened. Changes are in `src/**` only:
`src/ghostprimer/secrets.py`, `src/ghostprimer/memory.py`,
`src/ghostprimer/bundle.py`.

## D1 - Secret in a memory file exported verbatim (release-gating)

Two stacked causes, both fixed:

1. **Missing shape.** `secrets.py` had no pattern for `sk-` keys at
   all. A key sitting in prose ("The staging deploy key is sk-...")
   matched nothing: the generic-assignment pattern needs a
   `key|secret|token|password` label followed by `:` or `=`, and no
   provider pattern covered the shape. Agent A's earlier smoke passed
   because the AKIA shape was present. Added
   `openai-or-anthropic-key` (`sk-`, `sk-ant-`, `sk-proj-` forms),
   mirroring the pattern GhostSlice and GhostRecall already use, so
   both the fallback path and the Recall-bundle path (both scan via
   `secrets.scan_text`) now catch it.

2. **Environment redaction markers.** In this sandbox, a secret-shaped
   literal written to a file is stored and read back in redacted
   marker form, `<redacted_api_token_1>` (verified by probe: a fresh
   sk- string written to /tmp reads back as the marker, and the
   fixture value and conftest's PLANTED_SECRET hash identically). That
   marker is the on-disk form the planted value actually takes here,
   and no provider pattern matches it. Added a
   `redacted-credential-marker` shape for angle-bracket redaction
   markers: the marker stands where a credential value stood, so an
   item carrying one is blocked like any other flagged item instead of
   being copied into the pack. In an unredacted checkout the sk- shape
   above is what fires; both rules are needed, neither is test-specific
   (no planted value is hardcoded anywhere).

3. **Blocking granularity.** The fallback path blocked whole files;
   PLAN.md blocks the flagged memory *item*. `fallback_memory` now
   extracts items first and scans each item's text: a flagged item is
   excluded and recorded with path, item title, line, and shape names
   only (never the value); clean items from the same file are kept.
   The Recall-bundle path already blocked per item and is unchanged
   apart from the new shapes.

Manual verification (build of tests/fixtures/secretmem_project):
summary reports `blocked: 1` (was 0); the blocked record names
AGENTS.md / "Deploy notes" with shape only; a grep for the planted
value across every file in the bundle returns **0 hits**; the
"Deploy notes" section and its text are absent from PRIMER.md, and
the clean "Standing rules" item from the same AGENTS.md is kept.

## D2 - Unreferenced module sliced in; not-included list empty

`build_bundle` made every code file a candidate and included anything
that fit the budget, so selection was "everything that fits" instead
of the plan's "entry points plus highest fan-in". Selection now
partitions non-entry candidates using the import graph: a file the
graph knows (a key in `python_fan_in`) with zero fan-in is
unreferenced, so it is excluded from the slice and named in
`not_included` with the reason recorded. Files absent from the graph
are non-Python, where v0.1 builds no import graph; their fan-in is
unknown rather than zero, so they remain budget candidates as before.

Manual verification (starter fixture): slice is the 3 entry points
plus core.py (fan-in 4) and helpers.py (fan-in 2); not-included names
orphan.py and report.py (report.py is also imported by nothing in the
fixture, so the same rule names it); no orphan slice exists under
`files/`, and its marker text is absent from PRIMER.md.

## D3 - README extract omitted first paragraphs

`readme_extract` set `para_open` on a heading but cleared it on the
first blank line, and standard Markdown puts a blank line between a
heading and its paragraph, so every paragraph was skipped and only
headings survived. The extractor now skips blank lines after a
heading, then takes the first paragraph as the whole run of
consecutive non-blank lines, verbatim (extractive only, as before).
Verified in the built starter bundle: the intro paragraph and the
Usage paragraph ("Heat the furnace, place the blank...") both appear
in PRIMER.md under their headings.

## Gates held

Stdlib only, local only, no network, no push, no publish, no spend.
Findings and blocked records still carry shape names only; no secret
value is written anywhere by the guard.
