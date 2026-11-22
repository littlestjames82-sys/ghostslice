# GhostRecall - Fix Report (parent-directed, Agent B findings)

Date: 2026-10-14. Scope: `src/**` only (plus this file). No test was
edited or weakened. Gates respected: stdlib only, no network, no
push, no publish, no spend.

Files changed: `src/ghostrecall/sources.py`,
`src/ghostrecall/recall.py`, `src/ghostrecall/bundle.py`.

## Baseline (before fixes)

`python3 -m pytest tests -q` -> **21 passed, 2 failed, 1 xfailed**
(matches REPORT_B.md exactly; the 2 failures were F1, the xfail F4).

## F1 - superseded decision served as current, and pinned: FIXED

Two root causes, both fixed:

1. The supersession link never resolved. DECISIONS.md cites the old
   record by short id (`Supersedes: D-010`) while the record's title
   and item id are `D-010 (2026-02-01)` / `decision-d-010-2026-02-01`.
   `_resolve_superseded` in `sources.py` used an exact-match index,
   found nothing, and left D-010 `active`. It now registers every
   decision under its title/id slugs, every id-shaped token inside
   them (`D-010`), and slug prefixes, and resolves citations against
   that index. A `Superseded by:` declaration also marks its record
   superseded, resolved to the newer record's title when present.
2. Even when a record WAS marked superseded, `recall.select()`
   let pinning win: `if status == "superseded" and not pinned` was
   the only exclusion, so a superseded standing rule (tagged `rule`)
   was selected and marked pinned. `select()` now tests supersession
   FIRST, before pinning is even computed: superseded items go to
   not_selected with reason `superseded` unconditionally, and the
   dead "pinned-superseded" conflict branch is removed. The `rest`
   ranking already excluded superseded items and still does.
   `bundle.build_bundle()` adds defence in depth: any superseded
   entry handed to it is skipped as content and recorded in
   not_selected instead, so a superseded item can only ever appear
   in the manifest under `excluded` (mode `exclude`, status
   `superseded`), never as an item, never with `pinned: true`, and
   its text never reaches PROMPT.md.

Manual verification on the superseded fixture: bundle items are
D-011 (active, pinned rule, correctly) plus the release-notes doc;
excluded holds `decision-d-010-2026-02-01` (status superseded,
reason superseded); the old text is absent from PROMPT.md and the
new decision text is present.

## F1b - spurious conflicts for `Supersedes: none`: FIXED

`Supersedes: none` was stored as the truthy string `"none"`, so the
conflict generator fired for decisions that superseded nothing
(e.g. `current: D-010, superseded: none`). `sources.py` now
normalises none-like references (`none`, `no`, `n/a`, `null`, `-`,
empty) to `None` at parse time via `_clean_ref`, and `recall.py`
independently treats them as no supersession via `_real_supersedes`
(defence at both layers: parser and ranking/conflict generation).
Verified: recall on `examples/sample_project` prints no conflict
lines for its `Supersedes: none` decisions, and the superseded
fixture now produces exactly one conflict, the real one
(D-011 supersedes D-010).

## F4 - `check` did not validate PROMPT.md: FIXED

`check_bundle` in `bundle.py` now verifies PROMPT.md like any other
bundle content: against the new manifest field `prompt_sha256`
(written by `build_bundle` over the exact text written to disk),
and against `totals.prompt_tokens_estimate` (so bundles written
before `prompt_sha256` existed are still caught). A good bundle
checks OK; appending a line to PROMPT.md now fails check with both
`sha256 mismatch: PROMPT.md` and a token-total mismatch, exit 1
(verified manually on a copy).

Consequence for the test suite: `test_check_rejects_tampered_prompt`
is marked `@pytest.mark.xfail(strict=True)` in Agent B's suite.
The fix makes its assertion pass, so pytest reports it as
**XPASS(strict)**, which pytest counts as a failure. That is the
expected, welcome signal described in the task: **the parent needs
to remove that xfail marker** (test file was not edited here, per
instructions). Once the marker is removed the suite should read
24 passed.

## Final test result (honest)

`python3 -m pytest tests -q` -> **23 passed, 1 failed, 0 xfailed**,
exit 1. The single "failure" is the strict XPASS of
`test_check_rejects_tampered_prompt` described above, i.e. the F4
test now passing for real. The two previous F1 failures
(`test_old_decision_never_served_as_current`,
`test_old_decision_in_prompt_only_if_marked`) pass, as do the other
superseded tests (current decision exported, conflict flagged).
Nothing else regressed: provenance, secrets, modes/bundle, and
profile/boundary tests all pass (23 passed includes every test
except the XPASS-counted one).
