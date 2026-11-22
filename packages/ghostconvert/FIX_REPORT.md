# GhostConvert polish fix - parent-directed (REPORT_B observations 1 and 2)

Date: Oct 14, 2026. Scope: `src/**` only. No tests were edited or
weakened. Both fixes are wording/classification changes in the tool's
losses reporting; conversion behavior (order, bodies, verbatim labels,
immutability, exit codes) is unchanged.

## Fix 1 - emptied-by-design is no longer reported as a missing body

**Before:** any included entry with no body landed in one bucket:
LOSSES.md heading "Files with no readable body" and inspect's
"Missing bodies". A `strip-tests` entry GhostSlice deliberately emptied
(manifest `sliced_tokens: 0`, empty-string sha256) was worded the same as
a body that was actually lost.

**Change:**
- `src/ghostconvert/bundle.py`: new `BundleFile.emptied_by_design`
  property - no body, not excluded, and the manifest itself records that
  nothing was shipped (`sliced_tokens == 0`, or the entry's sha256 is the
  empty-string hash, pinned as `EMPTY_BODY_SHA256`). New
  `BundleFile.missing_body` property - no body and not emptied by
  design, i.e. the manifest promises content that is absent.
- `src/ghostconvert/convert.py` (`compute_losses`): two separate loss
  categories. Emptied entries get "Files emptied by GhostSlice (no body
  by design)", naming each file with its mode and stating Slice shipped
  no body on purpose, so nothing was lost in conversion. Genuinely
  missing bodies keep the existing "Files with no readable body"
  category and wording.
- `src/ghostconvert/cli.py` (`inspect`): prints "Emptied by GhostSlice
  (no body by design): <path> (mode: <mode>)" for the first class and
  "Missing bodies:" only for the second.

## Fix 2 - unknown modes are flagged as unrecognized, still carried verbatim

**Before:** a mode outside the known set (suite fixture: `banana-split`)
was converted with its label verbatim and counted in inspect's census,
but no output said the mode is unrecognized.

**Change:**
- `src/ghostconvert/bundle.py`: `KNOWN_MODES` - GhostSlice's own MODES
  tuple (`full`, `signatures`, `interfaces`, `structure`, `strip-tests`,
  `exclude`, `headings`) plus `symbols`, the symbol-level entry mode the
  bundle format documents. New `BundleFile.unknown_mode` property.
  Convert still imports no GhostSlice code (plan rule); the set is a
  pinned copy, commented as such.
- `convert.py` (`compute_losses`): new loss category "Unrecognized slice
  modes" naming each unknown label and the files carrying it, stating
  the label is carried verbatim and the file converted like any other,
  but GhostConvert cannot say what slicing the label means.
- `cli.py` (`inspect`): the mode census annotates unknown modes with
  "(unrecognized mode, carried verbatim)", and a summary line prints
  "Unrecognized mode(s): ..." when any are present.

## Verification

- Full suite, `python3 -m pytest tests -q` from `~/workspace/ghostconvert`:
  **58 passed, 0 failed** (baseline before the fix: 58 passed, 0 failed -
  no regressions, no test changes).
- Demo fixture (hand-built bundle in /tmp with one entry per class:
  `src/app.py` full with body, `tests/test_app.py` strip-tests with
  `sliced_tokens: 0` and the empty-string sha256 and no body,
  `src/lost.py` full with `sliced_tokens: 25` and no body anywhere,
  `src/weird.py` mode `banana-split` with body). `inspect` printed the
  census annotation, the "Unrecognized mode(s): banana-split" line,
  "Emptied by GhostSlice (no body by design): tests/test_app.py
  (mode: strip-tests)", and "Missing bodies: src/lost.py" - each file in
  exactly one class. The agents conversion's LOSSES.md carries the two
  body categories separately (emptied: `tests/test_app.py`; no readable
  body: `src/lost.py` only) plus the "Unrecognized slice modes" entry
  for `banana-split`, and AGENTS.md still shows the verbatim section
  header `## File: src/weird.py (mode: banana-split)`.

## Observation left for the parent (not changed, outside the two assigned fixes)

`inspect`'s summary line reads "Files: N (X with bodies, Y excluded)"
where X is really the included (non-excluded) count, including bodyless
entries. The per-class lines below it are now exact, but the census
label itself still says "with bodies". One-word rewording candidate for
a future polish round; left untouched to keep this fix scoped.

## Gates held

Python standard library only, local only, no network, no GitHub push,
no PyPI or publish step, no announcements, no spend. No em dashes in
this report.
