# G17 Audit — Dashboard v2: slice preview + what-if (v0.22.0)

Goal: the dashboard gains the side-by-side Slice Preview from Ryan's
mockups (original vs slice, token delta in the header, live mode
switcher) and a What-if panel (mode override, budget/fit slider,
exclude-secrets / redact / auto-shrink toggles) whose Recalculate
returns would-be totals WITHOUT writing anything, plus export-from-
preview carrying the panel's options. Baseline: v0.21.0, 642 tests
passed.

## Build summary

- `GET /api/slice?path=<rel>&mode=<mode>` (new): {path, mode,
  language, original, sliced, original_tokens, sliced_tokens,
  saved_tokens, saved_pct, truncated, truncated_sides, note}.
  Content comes from the scan index only. Path safety is defence
  in depth (state.preview_entry): the raw rel must be relative,
  backslash-free, and free of `..` segments (parse_qs has already
  URL-decoded, so %2e%2e arrives as `..` and is caught); the file
  must be in the scan; and the file's RESOLVED path must stay
  inside the resolved project root — the scanner follows file
  symlinks, so a link pointing outside is scanned but its content
  is refused (403), while a link resolving inside is served.
  Each side is capped at 200,000 characters with an in-band marker
  and a truncated flag; token counts always describe the full
  text. Slices are memoised per (path, mode) on the state (the
  dashboard is a startup snapshot; the mode-token table already
  was), flushed at 256 entries, lock-guarded.
- `/api/preview` (existing) now goes through the same containment
  check and the memoised slicer; response shape unchanged.
- `POST /api/whatif` (new): validated panel options (mode in MODES,
  fit a positive int, toggles boolean, selections a path->mode
  map) -> whatif_payload: candidate totals, the plain-default-
  export baseline, delta, mode-change diff (capped at 100 files +
  flag), the fit report when a budget is set, and honesty notes.
  The totals come from `_totals_for_options`, which runs the
  exporter's own machinery in the exporter's order —
  resolve_modes_detailed, fit_modes (pre-redaction ladder), then
  per-file slice_text + redact_text + recount — so the what-if is
  not a second estimator. It writes nothing and records no
  history (it never calls build_bundle).
- `POST /api/export` (extended): the same validated panel options
  ride along (default_mode / fit / exclude_secrets / redact /
  auto_shrink) and are passed to build_bundle, so what was
  previewed is what gets exported; the response gains the
  manifest's fit / redaction blocks when present. It also now
  passes the state's profile — see F2.
- dashboard.html: the preview pane is now two panes (Original |
  Slice) with a mode switcher synced with the table; file content
  is assigned via textContent only. New What-if card: mode
  override select, budget range+number (0 = off), the three
  toggles, Recalculate, and a results line that names the delta
  vs a default export and the fitted verdict. The Export button
  sends the panel options with the selections.
- Tests: tests/test_v22_dashboard.py, 27 at build (slice ground
  truth vs slice_text, mode switching, traversal battery, symlink
  out/in, truncation with full-text tokens, 8-thread concurrency,
  what-if ground truth vs build_bundle for 8 option combinations,
  what-if writes-nothing fs snapshot, export honours options,
  page markup, XSS payload inertness). Full suite at build:
  669 passed, 1 skipped (642 baseline unweakened).

## Audit #1 — adversarial review of the build

### F1 [LOW] /api/preview error precedence flipped
The old handler resolved the entry (404) before validating the
mode (400); the build validates the mode first, so a request with
both a bad path and a bad mode now answers 400 instead of 404. No
test pins it and both are client errors, but gratuitous deltas
from the pre-existing surface are how regressions sneak in.
Fix (Improve #1): restore entry-first in /api/preview.

### F2 [MED] Dashboard export ignored the project profile (pre-existing, now fixed — behaviour change, called out)
Until this goal, /api/export called build_bundle WITHOUT the
profile, while the dashboard's own scan honours it: on a project
with .ghostslice.json ignores/modes, the dashboard showed one
selection and exported another (ignored files were bundled).
The build passes state.profile, aligning the dashboard export
with the CLI export and with the what-if baseline (defined as a
plain profile-honouring export). Existing dashboard tests use
profile-less fixtures and are unaffected; the change is recorded
here and in the CHANGELOG because it is a real behaviour change
for profiled projects, in the direction of consistency.

### F3 [MED] What-if ground truth unpinned for profiled projects
The build's ground-truth fixture has no .ghostslice.json, but a
profile changes the machinery the what-if shares: profile modes
are fit-protected, entry points are fit-protected, and profile
redact/auto_shrink are the defaults both sides fall back to. The
code paths are the same functions build_bundle calls, but "same
functions" is a claim the test suite should pin, not prose.
Fix (Improve #1): a profiled-fixture ground-truth class (profile
modes + entry point + a fit budget that would downgrade both).

### F4 [LOW] Three option combinations unpinned
exclude_secrets+redact together (exclusion wins; redaction covers
the rest — the precedence the CLI documents), selections+fit
(the selection must be downgrade-protected on both sides), and a
global mode override of "exclude" (resolve_modes applies a
caller default only to slicable non-test files; both sides share
resolve, but pin it). Fix (Improve #1): three more ground-truth
combinations.

### F5 [LOW] Empty project not exercised
A zero-file project makes every total 0 and saved_pct a division
by a guarded zero. Fix (Improve #1): one test — what-if returns
zeros with fitted null, and /api/slice 404s cleanly.

### Checked, no defect
- Traversal: double slashes and `./` prefixes miss the scan index
  (404); %252e double-encoding stays a literal filename (404);
  absolute Windows-style paths carry a backslash (400); a `..`
  segment anywhere — even one that would resolve back inside
  (sub/../app.py) — is refused (400), deliberately stricter than
  resolution: the UI only ever sends scan paths verbatim.
- Symlink race: containment is checked per request on the
  resolved abspath, so a file swapped for an escaping symlink
  after the scan is refused at request time.
- Directory symlinks are never descended by os.walk
  (followlinks=False) and so are never in the scan (404).
- Redact in the what-if is exact, not approximate: the same
  redact_text runs on the same slice text and the recount uses
  the same estimator call build_bundle makes; the response says
  totals are post-redaction. Fit+redact mirrors build_bundle's
  redacted_after_tokens bookkeeping.
- Concurrency: the what-if reads only immutable scan state; the
  slice memo is lock-guarded; 8 parallel /api/slice requests
  return byte-identical bodies (test-pinned).
- Content types: both new endpoints answer application/json via
  the shared _json helper; the page stays text/html.
- The what-if writes nothing: fs-snapshot test covers file bytes,
  the history ledger, the cache dir, and bundle dirs.

## Audit #2 — fresh probes on the improved state

Probes (standalone, against live servers): profile-default
fallbacks (a profile setting redact:true and auto_shrink:true,
with panel overrides turning each back off), the export `out`
parameter, the preview request flow, and a re-run of the full
campaign (34 + 642 tests green).

### F6 [MED] /api/export `out` escaped the project root
The handler's own comment promises the bundle "always lands
inside the served project", but out was joined unchecked:
`{"out": "../escaped"}` wrote a full bundle OUTSIDE the root
(probe-confirmed, directory created). A write primitive that
contradicts its stated contract — the read endpoints got
containment in this goal; the write endpoint gets it now.
Fix (Improve #2): the resolved output path must stay inside the
resolved root (a nested "bundles/x" still works); anything else
is a 400 before build_bundle runs. Test-pinned.

### F7 [LOW] Preview response race in the page JS
Rapid file clicks fire overlapping /api/slice fetches; a slow
earlier response could land after a later one and paint the
wrong file's panes under the newer file's name. Fix (Improve
#2): a monotonically increasing request sequence in preview();
only the latest response paints.

### Checked, no defect
- Profile defaults as ground truth: profile {redact: true,
  auto_shrink: true} — what-if defaults, mode override, and
  explicit panel overrides of each profile default all match a
  real build_bundle manifest exactly (probe; the redact+full
  combination legitimately slices to MORE tokens than the
  original estimate — placeholders are longer than the values —
  and both sides agree on the number). Pinned as tests in
  Improve #2.
- A what-if on a file deleted after startup degrades to
  {ok: false, error} via the handler net — no traceback, the
  G16 invariant holds on the new endpoints.
- HEAD/unknown methods keep BaseHTTPRequestHandler's 501;
  unknown POST paths 404; non-object JSON bodies 400 (v0.21).

## Limitations (documented in README)
- The dashboard is a startup snapshot: files changed on disk
  after `serve` starts are previewed from their current bytes
  only where a slice is not yet memoised, and the scan (file set,
  secret findings, token table) never refreshes. Same semantics
  the dashboard has always had; a rescan endpoint is future work.
- The preview cap counts characters, not bytes; a 200k-character
  pane of astral-plane text is a larger JSON payload than one of
  ASCII, though bounded by construction.
- Pre-existing, out of scope: the file TABLE renders paths via
  innerHTML (a hostile filename is an injection surface in the
  list view). The new preview/what-if surfaces use textContent
  throughout; the table predates this goal and is unchanged.

Final state: 679 tests passed (642 baseline + 37 new in
tests/test_v22_dashboard.py), 1 skipped (the pre-existing root
chmod skip); the 642 existing tests are unweakened;
`ghostslice secrets .` exits 0; version 0.22.0.
