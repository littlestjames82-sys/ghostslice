# GhostConvert v0.1 - polish round report

Date: Oct 14, 2026. Directed by Ryan ("Polishing") after Wave 4 parent
verification. Sole folder owner for this round. In-tree polish only: no
version bump (still 0.1.0), no push, no publish, no announcements, no
spend, stdlib only. Theme of the round: every number and label the tool
prints must be exact. All changes are wording/classification fixes in
output text; conversion behavior (order, bodies, verbatim labels,
immutability, exit codes, guards) is unchanged.

## Test counts

- Before: **58 passed, 0 failed** (parent-verified baseline, re-run by
  me at the start of this round: 58 passed in 18.33s).
- After: **63 passed, 0 failed** (58 existing, none weakened or deleted,
  plus 5 new regression tests in `tests/test_polish.py`).

## What changed

1. **inspect census line made exact** (`src/ghostconvert/cli.py`).
   The seed candidate from FIX_REPORT.md, confirmed in audit: the line
   read "Files: N (X with bodies, Y excluded)" where X was
   `len(bundle.included)`, the non-excluded count, which includes
   bodyless entries. It now prints the real partition: with bodies
   (included, body present), emptied by GhostSlice, missing bodies,
   excluded. The bodyless segments appear only when nonzero, and the
   counts always sum to the total. Demonstration on
   `examples/sample_bundle`: old line would have claimed "Files: 7
   (6 with bodies, 1 excluded)"; the new line reads "Files: 7
   (5 with bodies, 1 emptied by GhostSlice, 1 excluded)".

2. **inspect totals line no longer prints None** (`cli.py`). A manifest
   without totals produced "Totals: None sliced of None original
   estimated tokens (method: unknown)". It now prints "Totals: not
   recorded in the manifest". The normal totals line is unchanged (the
   existing contract test still passes on the golden bundle).

3. **Artifact headers no longer print "saved None"**
   (`src/ghostconvert/convert.py`). When a manifest records sliced and
   original totals but no `total_saved_tokens`, the header claimed
   "(was N, saved None)". The saved clause is now included only when
   the manifest records it: "(was N, saved Z)" when present,
   "(was N)" when absent. Nothing is recomputed or invented; the
   manifest stays the only authority.

4. **Emptied-by-design wording made exact** (`convert.py`). The loss
   detail said "the manifest records sliced_tokens 0 for each", but
   `BundleFile.emptied_by_design` also classifies via the empty-string
   sha256. The detail now reads "the manifest shows each one as an
   empty slice", which is true under either signal.

5. **Shipped examples regenerated** (`examples/converted/`). All four
   committed `LOSSES.md` files still carried the pre-fix wording,
   listing `tests/test_app.py` under "Files with no readable body".
   Regenerated with the documented command
   (`convert examples/sample_bundle --to all -o examples/converted
   --force`). Diff against the pre-round copy: only the four
   `LOSSES.md` files changed, and only the emptied category heading
   and its text; every converted artifact is byte-identical.

6. **README losses section documents the two distinctions**
   (`README.md`). It now states that emptied-on-purpose files are
   listed separately from genuinely missing bodies, and that
   unrecognized modes are flagged while their labels are carried
   verbatim, matching the behavior the fix round shipped.

7. **Regression tests added** (`tests/test_polish.py`, 5 tests,
   black-box, built on the suite's hand-bundle helpers): census counts
   sum to the total on a bundle with one file in each class; the
   common body-plus-excluded case keeps the short line; missing totals
   are named, not printed as None; the saved clause is omitted when
   the manifest lacks `total_saved_tokens` and kept verbatim when it
   records it.

## Deliberately left alone

- `IMPLEMENTATION_A.md` item 2 and `REPORT_B.md` observations 1 and 2:
  historical build records describing the pre-fix behavior. They are
  superseded by FIX_REPORT.md and by this report; editing them would
  rewrite the record of what the builders found and when.
- FIX_REPORT.md's closing observation paragraph: it describes the
  census line as it stood when that fix landed. Item 1 above is its
  resolution.
- A manifest entry whose path escapes the bundle is still also counted
  among missing bodies in inspect and LOSSES.md when it carries no
  body. It is separately named under "Skipped (paths escape bundle)"
  in both outputs, so nothing is hidden, and reclassifying it would
  change category semantics beyond this round's wording scope.
- The mode census counts excluded entries under their mode (an
  `exclude` entry counts toward "mode exclude"). As labelled it is a
  census of manifest entries by mode, and it is exact as such.
- No renderer, loader, guard, or exit-code behavior was touched; the
  diff in `src/` is confined to printed strings and the conditions
  that choose them.
