# GhostData merge record (Oct 18, 2026)

Merged tree built from the pristine tree (`~/workspace/ghostdata/`, untouched)
plus the three improvement lanes, applied in order: harden, then polish,
then deepen. Method: single-lane files copied directly; multi-lane files
combined with a three-way merge (pristine as base) and every conflict
resolved by hand so both sides' changes survive.

## Final test counts

Command: `python3 -m pytest -q` in the merged tree.

- Pristine baseline: 63 passed
- harden lane: 84 passed (63 + 21 new in tests/test_harden.py)
- polish lane: 63 passed (no new tests, docs/help/docstrings only)
- deepen lane: 74 passed (63 + 11 new in tests/test_date_range.py)
- **Merged: 95 passed, 0 failed** (63 + 21 + 11; zero new failures versus
  every lane, and more passing than the best single lane)

## Which files came from which lane

Copied from one lane only:

- tests/test_harden.py: harden (new file)
- tests/test_date_range.py: deepen (new file)
- examples/README.md, src/ghostdata/__init__.py,
  src/ghostdata/__main__.py, src/ghostdata/cli.py,
  src/ghostdata/tokens.py: polish

Hand / three-way merged (multiple lanes):

- src/ghostdata/core.py: harden + polish
- src/ghostdata/mcp_server.py: harden + polish
- src/ghostdata/pack.py: harden + polish
- src/ghostdata/readers.py: harden + polish
- src/ghostdata/sensitive.py: harden + polish
- src/ghostdata/infer.py: harden + polish + deepen (see below)
- README.md: polish + deepen (three-way merge, no conflicts; the polish
  Install / Quick start / Exit codes sections and the deepen date-range
  schema bullet and honest-limits notes are all present)

No other files differ from pristine. No IMPROVE.md files were carried into
the merged tree.

## Conflicts and how they were resolved

1. core.py, `sample_indices` (harden vs polish): polish expanded the
   docstring, harden changed the guard to
   `if total <= 0 or sample_size <= 0:`. Resolved with the polish
   docstring AND the harden guard. No logic dropped.
2. readers.py, `_dedupe_names` (harden vs polish): polish added a
   docstring where harden had placed its collision-avoidance comment.
   Resolved with the polish docstring followed by the harden comment;
   the harden collision-avoidance body is unchanged.
3. sensitive.py, `name_reason` (harden vs polish): a real rewrite
   conflict. Harden replaced the substring NAME_PATTERNS loop with
   whole-word token matching (split on separators and camelCase
   boundaries); polish only added a docstring to the old implementation.
   Resolved by keeping the harden whole-word implementation in full
   (this is the deliberate, tested behavior change and it survives
   verbatim, including `_name_tokens`, the compound list, rule order, and
   the original reason strings) and placing the polish docstring above
   it. The old substring loop is gone, not duplicated.
4. infer.py, `ColumnStats.add` (harden vs deepen): the predicted real
   conflict, detailed below.
5. mcp_server.py, pack.py, and the polish layer of infer.py merged
   cleanly in the three-way merge (harden logic and polish docstrings
   were in different regions); verified afterward that both sides are
   present (for example pack.py keeps harden's sample recount /
   row_indices check and polish's docstrings; mcp_server.py keeps
   harden's TypeError/AttributeError handling and polish's docstrings).

## The infer.py hand-merge: shape checks AND date ranges

Pristine `ColumnStats.add()` updated the numeric range first and ran the
shape check afterwards. Harden reordered it (shape check first, shape-
matching and non-finite values excluded from min/max, stable NaN key in
`_distinct_key`); deepen inserted earliest/latest date tracking
immediately after the old numeric update and suppressed it for
unparseable or mixed columns. Those two edits touched the same region,
so they were hand-merged as follows, in this exact order in the merged
`add()`:

1. Distinct counting first, unchanged, including harden's NaN key fix in
   `_distinct_key`.
2. Harden's shape check runs next and BEFORE any range update: string
   values go through `sensitive.shape_of`, native ints through
   `sensitive.shape_of_int`, hits are recorded once in `shape_hits`.
3. Harden's numeric range update follows, guarded by
   `numeric is not None and shape is None` plus the `math.isfinite`
   check, so a card/phone-shaped or non-finite value can never become
   the printed min/max. There is exactly one numeric range update site
   in the merged file (deepen's copy of the old unconditional update was
   removed, not duplicated).
4. Deepen's date tracking runs last, as its own block:
   `if kind == "date" and isinstance(value, str)`, it computes
   `date_sort_key(value)` (chronological comparison, UTC normalisation,
   date-only at start of day), sets `date_unparseable` when a date-shaped
   value is not a real calendar date, and otherwise updates
   `date_min`/`date_max` keeping the source spelling. One deliberate
   tidy: the local is named `date_key` instead of deepen's `key`, so it
   cannot clobber the distinct-count key computed in step 1 (deepen's
   original reused `key`; behavior is identical because that key is not
   used again in `add()`, and the rename removes the hazard).
5. `to_dict()` keeps both lanes: harden behavior is in `add()` /
   `_distinct_key`; deepen's emission adds `min`/`max` from
   `date_min`/`date_max` only for a pure date column with no unparseable
   value, and it sits inside the non-redacted branch, so a redacted date
   column still reports min/max as null, exactly like deepen specified.
   Imports carry both `math` (harden) and
   `datetime`/`timezone` (deepen); the module docstring carries deepen's
   range paragraph, and the ColumnStats/add/to_dict docstrings are
   polish's.

Both behaviors are pinned by the merged suite: tests/test_harden.py
(shape-before-range leak, NaN/Infinity strict-JSON manifest) and
tests/test_date_range.py (timezone normalisation, suppression rules,
20,000-row true counts) all pass together.

## Anything suspicious

- Nothing flagged. No harden fix was dropped: the merged tree passes all
  21 harden tests and all 11 deepen tests simultaneously, and the changed
  file set is exactly the union of the three lanes' changed files.
- The one judgment call is the `key` to `date_key` rename noted above;
  it is behavior-neutral and documented here rather than silent.
