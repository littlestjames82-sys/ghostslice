# G05 Audit — Token estimator calibration (v0.10.0)

Goal: per-language-family calibration factors on the BPE-like raw
split, golden corpora, `ghostslice calibrate`, consistent method
string; plus carried parent finding P0. Baseline 276 tests; build
brought the suite to 291 (15 new in tests/test_v10_calibration.py,
including the P0 tests and the corpus characterization).

## P0 (carried parent finding, fixed FIRST, before the G5 build)

Symptom as reported: in G4 structure mode, YAML lines whose values
are placeholdered by the scanner backstop (configslice
`_leak_backstop`) were emitted at column 0 — `password:` /
`api_token:` lines nested under `database:` losing their indent,
which in YAML silently promotes the keys to top level.

Investigation (probe battery, all measurements numeric because the
tool-output display redacts secret-shaped spans and mangles the
surrounding whitespace — the same artefact appears to explain the
original sighting): nested backstop-only values (AKIA-shaped token
under `access_id`), deep nesting (indent 6), quoted keys, dotted
keys, anchors, flow maps, sequence-item maps, JSON (indent 4),
TOML, CRLF sources and 4-space indents. In the v0.9.0 build every
rewrite already preserved indentation: the regex path's group(1)
begins with `\s*`, and the fallback path re-adds the line's indent
explicitly. No shape reproduced a literal column-0 rewrite.

Fix applied anyway, because the guarantee was incidental, not
structural: `_leak_backstop` now computes the original line's
leading whitespace FIRST and builds every replacement as
indent + body (the value regex now matches against the
indent-stripped body). One adjacent real defect the battery did
surface: the fallback path replaced a flagged sequence-scalar line
wholesale, dropping its `- ` marker (indent survived; the dash did
not) — the fallback now preserves a leading `- ` too. Regression
tests pin all of it: backstop-only nested (indent 2 and 6),
value-rule nested placeholder, key-rule nested placeholders
(`password`/`api_token` under `database:`, the reported shape),
sequence scalar (indent + dash), JSON nested (indent 4).
Files: src/ghostslice/configslice.py, tests/test_v10_calibration.py
(TestP0BackstopIndent).

## Audit #1 (after build)

### F1 [MEDIUM] tokens.py docstring contradicts the family map
The module docstring says sql/shell/powershell/"notebook-others"
map to "other" (factor 1.0), but `_LANGUAGE_FAMILY` maps
"notebook" -> "python" (0.86). The code's choice is the defensible
one (a sliced notebook renders as code cells, so the python factor
fits the sliced side; the raw JSON side inherits it as an
approximation), but the docstring is the calibration's evidence
record and must not misstate the map. Fix the docstring.

### F2 [LOW, reviewed — behaviour kept, now pinned] Minified family can flip between a file's original and sliced estimates
`family_for` derives the family from the text passed in, so a
minified JS file's original is estimated as minified-js (0.65)
while its short signatures slice is estimated as ts-js (0.75).
This looks like an inconsistency but is load-bearing: exporter
validation must reproduce build-time sliced totals from the bundle
alone, and the bundle only contains the sliced text — per-text
family derivation is exactly what makes build and validate agree
in all cases (pinning the family to the source text would make
bundles containing minified sources fail validation). Distortion
is bounded: it affects only minified sources, whose slices are
small next to their originals. Keep; pin with a bundle test over
a minified file (validate must pass), and state the behaviour in
the tokens.py docstring.

### F3 [LOW] Factor evidence rests on one sample per family
Each golden corpus is a single hand-written sample of 0.7-2.1 KB.
Implied chars/token on one small sample carries sampling noise;
a different sample of the same language would move the second
decimal. Mitigations already in place: factors are rounded to two
decimals, the characterization tolerance is ±12%, and the targets
are published anchors, not measurements of a real tokenizer (the
docstring says so). Fix: state the one-sample limitation
explicitly in tokens.py so the evidence record is complete.

### F4 [INFO, no findings] Double-application hunt
Exactly three production call sites exist (scanner per-file,
slicer per-slice, exporter validate recompute); all now pass the
language. fit.py, watch.py, selection.py, report.py, server.py,
mcp_server.py and exporter.estimate_context_tokens consume
entry.tokens or slice_text results — no second estimator and no
chars/4-style logic outside tokens.py (grepped). Inside
estimate_context_tokens, `before` mixes entry.tokens (full /
exclude branches) and slice r.original_tokens (sliced branches);
both are estimate_tokens(source, language) over the same text, so
the values are identical by construction.

### F5 [INFO, no findings] Calibrate/scan agreement
calibrate_project groups the scanner's own result and re-reads
each file, so its calibrated total equals scan's total on a static
tree (pinned by test, including a minified-js file whose family
depends on text). A file edited mid-report could desync the two
commands run at different times — the same caveat any two scans
have; not a defect. Dashboard and MCP quote scan/estimate numbers
only, and all three method strings (manifest, scan JSON,
dashboard, MCP) now come from the single tokens.METHOD constant;
report.py's hard-coded sentence was updated to the same v2 wording.

### F6 [INFO, no findings] Rounding and budget behaviour
Calibrated = int(raw * factor + 0.5) with all factors <= 1 can
never exceed the raw count, and is 0 iff raw is 0, so ordering
and zero behaviour are preserved. check-budget / fit consume
calibrated totals from v0.10 on; the migration note (totals drop,
re-check budgets tuned under v0.9) is in README, CHANGELOG and
the tokens.py docstring, with the measured GhostBus shift
(165,052 -> 129,555 original; 53,339 -> 45,770 sliced).

### F7 [INFO, no findings] Overclaim scan of new docs
README/CHANGELOG/docstring claims checked sentence by sentence:
every accuracy claim is anchored to "published rule of thumb" or
labelled an approximation; the corpus is described as the
characterisation surface, never as a comparison against a real
tokenizer; the OpenAI anchor is cited only for the English-text
rule it actually publishes. One wording fix rides with F1/F3.

## Improve #1 (fixes applied)
- F1: tokens.py docstring corrected — notebook maps to the python
  family (sliced notebooks render as code), sql/shell/powershell
  and unknown labels map to "other".
- F3: tokens.py docstring now states the corpora are one
  representative sample per family and that implied rates carry
  sampling noise at the second decimal.
- F2: tokens.py docstring documents the per-text family derivation
  and why (bundle validation must reproduce sliced totals from
  the bundle alone); new test builds a bundle containing the
  minified corpus file and asserts validate_bundle passes and the
  family flip is the documented one.

## Audit #2 (of the build + Improve #1 fixes)

### G1 [verified] Cross-command agreement on a real tree
On GhostBus via the CLI: `calibrate --json` calibrated total =
129,555, exactly `scan --json`'s total_tokens, and calibrate's
raw total = 165,052, exactly the recorded v0.9 demo originals —
so the before/after shift in README/CHANGELOG (165,052 ->
129,555 original; 53,339 -> 45,770 sliced via build_bundle on the
same tree, bundle validates) is a pure estimator change on an
unchanged tree, not tree drift. scan --json carries the v2 method
string from tokens.METHOD.

### G2 [verified] Edge shapes
`calibrate` on an empty project exits 0 in text and --json modes
(zero totals, implied 0.0, no division by zero). The dashboard
server suite (which exercises the new TOKEN_METHOD import in
server.py) passes unchanged.

### G3 [LOW, fixed in Improve #2] Evidence table was not pinned
The characterization test proves corpora land on targets, but
nothing stopped a future edit to a corpus sample from silently
changing the raw implied rates quoted in tokens.py's evidence
table, leaving the docstring citing numbers the corpora no longer
produce. Improve #2 pins the documented v1 implied rates in the
test file (±5%): a corpus edit that moves the evidence now fails
a test and forces the docstring/factor review it should.

### G4 [INFO, no findings] Re-check of Improve #1 edits
The corrected docstring mapping sentence now matches
_LANGUAGE_FAMILY exactly (notebook->python, yaml/toml->json-data,
sql/shell/powershell/text->other). The F2 bundle test asserts the
flip rather than hiding it: original family minified-js, sliced
tokens equal to a direct ts-js estimate of the slice, bundle
validates. Rounding/monotonicity (F6) re-verified by the
unchanged test_tokens.py values on the no-language path.

## Improve #2 (fixes applied)
- G3: TestCorpusEvidencePin added — documented v1 implied rates
  pinned per family against the corpora.

Final state after Improve #2: full suite green (see handoff for
the count), `ghostslice secrets .` exits 0, version 0.10.0.
