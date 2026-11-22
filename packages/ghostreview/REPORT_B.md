# GhostReview v0.1 - Agent B Report (tests / docs / examples)

Status: COMPLETE. Final result against Agent A's finished CLI:
**43 passed, 0 failed, 0 skipped** under pytest (run three times,
including once with no PYTHONPATH set, since helpers set it for
the subprocess). Breakdown: 25 CLI review tests, 17 fixture
tests, 1 MCP test.

## What Agent B built

File ownership respected: only `tests/**`, `README.md`,
`examples/**`, and this `REPORT_B.md` were created or edited.
No edits to `src/**`, `pyproject.toml`, or `PLAN.md`. Agent A's
PLAN.md and core landed during this run and the suite was
aligned to them (details below).

- `tests/helpers.py` - black-box CLI discovery (GHOSTREVIEW_CMD,
  `ghostreview` on PATH, or `python -m ghostreview` with
  PYTHONPATH=src then repo root) + runner, lenient output finder
  (REVIEW.md / review.json), tree hashing for working-tree
  safety, a minimal diff parser and secret/test path matchers
  used only to validate the planted fixtures.
- `tests/conftest.py` - `collect_ignore_glob = ["fixtures/**"]`
  so pytest does not collect the fixture project's own
  test_pricing.py as a GhostReview test (same fix GhostScope
  needed).
- `tests/fixtures/diffs/` - planted diffs: clean_small,
  test_edit, secret_path (.env + config/credentials.json),
  secret_shaped_line (a quoted fake assignment in a normal
  settings.py), large_deletion (a whole file, 120 deleted
  lines), deleted_test, config_change (pyproject.toml +
  CI workflow), symbol_removed, binary_change, new_file,
  rename, mixed_risky (test edit + secret path + deleted file
  in one diff), empty, malformed. The only secret-like value
  anywhere is the labelled fake marker
  `FAKE-SECRET-VALUE-12345-not-real`.
- `tests/fixtures/reports/` - verify-report.json in the real
  GhostVerify shape (verdict gaps_found, exit_code 1, gaps list,
  post verdict/tests) and scope.json in the real GhostScope
  scope.json shape (files list with risk_reasons, plus a
  scope_pack/ copy), so the optional-input tests exercise what
  Agent A's readers actually parse.
- `tests/fixtures/sample_project/` - app.py imports
  pricing.compute_total; tests/test_pricing.py covers it. This
  pins the plan's dependent test: a diff touching pricing.py
  must list app.py as a dependent, an unrelated diff none.
- `tests/test_fixtures_static.py` (17 tests, no CLI needed) -
  every planted fixture is what the CLI tests claim it is, and
  the report fixtures match the real Verify/Scope shapes.
- `tests/test_cli_review.py` (25 tests) - both outputs written
  and REVIEW.md numbers match review.json; plain-English naming
  + static-evidence honesty wording; verdict vocabulary;
  one test per plan risk rule (TEST-EDIT incl. deleted test,
  SECRET-PATH, SECRET-SHAPED-LINE, LARGE-DELETION, CONFIG /
  DEPENDENCY, SYMBOL-REMOVED, BINARY, VERIFY-FAILED driving
  needs-attention + exit 1); fake secret value absent from
  stdout, stderr, REVIEW.md, and review.json in both secret
  tests; Verify and Scope reports cited when supplied, and
  "no report was provided" stated plainly when not; dependents
  listed / not invented; empty diff is could-not-review with
  exit 2 (plan honesty bar); malformed and missing diffs never
  exit 0; the project tree is never modified.
- `tests/test_mcp.py` - stdio handshake: skips unless `mcp`
  answers initialize + tools/list, then asserts `review_diff`.
  It passed against the real server (not skipped in the final
  run).
- `README.md` - install (pip and PYTHONPATH routes), quickstart,
  command table, verdict derivation rule, exit codes (0
  straightforward/needs-a-look, 1 needs-attention, 2
  could-not-review), the full risk-rule table with the plan's
  thresholds (100 lines one file / 300 total / whole file),
  report formats, dependents honesty (one-hop import scan, not
  blast radius), limits stated plainly, scope, tests, layout.
- `examples/` - sample project (same shape as the fixture
  project), seven diffs, both sample reports, a walkthrough,
  and `sample_output/` (REVIEW.md + review.json labelled
  SAMPLE SHAPE ONLY, hand-written, not a captured run).

## Alignment to Agent A's landed core (read-only)

Written first against the task scope, then aligned once
PLAN.md + src landed mid-run:

1. Canonical CLI confirmed exactly as assumed:
   `ghostreview review <project> --diff <file> -o <out>` with
   `--verify-report` and `--scope-pack` (not `--scope-report`;
   helpers were corrected). Helpers still try a small set of
   argument-shape variants on usage errors only.
2. Empty-diff behaviour corrected to the plan: exit 2,
   could-not-review, never straightforward. The earlier lenient
   test (accepting 0) was replaced with the strict plan test.
3. Exit-code semantics pinned from cli.py/core.py: 0 for
   straightforward / needs-a-look, 1 for needs-attention, 2 for
   could-not-review. VERIFY-FAILED test asserts exit 1.
4. Verify fixture reshaped to the fields inputs.py reads
   (verdict, exit_code, gaps/soft_gaps counts, post.verdict,
   post.tests.status). Scope fixture reshaped to the files-list
   scope.json inputs.py reads (risk_reasons per file).
5. One Agent B test bug found and fixed: the static Verify
   fixture test expected a `class` field on gaps; real
   GhostVerify hard gaps carry file/symbol/reason/via with the
   verdict + exit_code on the report. The test now asserts the
   real shape.

## Manual verification (matches the tests)

- Clean example: exit 0, verdict straightforward, pricing.py
  3 added / 1 deleted, compute_total named as touched symbol,
  dependents app.py + tests/test_pricing.py, "No GhostVerify
  report was provided" stated.
- Mixed example with both optional reports: exit 1,
  needs-attention; flags VERIFY-FAILED, SECRET-PATH,
  LARGE-DELETION, SYMBOL-REMOVED (legacy_total), TEST-EDIT;
  Verify cited as gaps_found / exit 1 / 1 hard gap; Scope cited
  with its 3 risk reasons (6 callers, exported API, high blast
  radius).

## No core defects found

Every plan risk rule fired on its planted fixture, secret values
never leaked, empty/malformed input never produced a clean
verdict, and no output landed in the project tree. One cosmetic
note for the parent: the sample_output/ files in examples/ are
hand-written shape illustrations (labelled as such), so their
counts intentionally do not match a live run of mixed_risky.

## Gates honoured

Local only, stdlib only in tests, no push, no publish, no
announcements, no spend. Tests run the core as a local
subprocess against copies of the fixtures in temp dirs, so
checked-in fixtures are never written to by a run.
