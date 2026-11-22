# GhostReview v0.1 - Implementation A (core)

Agent A, Oct 14, 2026. Core only: PLAN.md, pyproject.toml, src/**.
Agent B owns tests/README/examples (landed in parallel, see Cross-check).

## What was built

PLAN.md in Slice format (same shape as GhostVerify's plan): problem,
position in the stack, pairing, MVP, out of scope, estimate, pricing
draft (not decided), verification bar, risks, next gate. The plan
states the boundary twice: GhostScope builds the change-centred review
PACK, GhostVerify runs sufficiency/patch CHECKS, GhostReview is only
the human-readable VERDICT layer on top. It builds no pack, runs no
check, applies no patch, runs no tests, calls no model.

CLI (stdlib only, local only, no network):

    ghostreview review <project> [--diff <file.diff> | --staged]
        [--verify-report <verify-report.json>]
        [--scope-pack <pack-dir|scope.json>]
        [-o <out-dir>] [--no-report] [--json]
    ghostreview mcp

- Default diff source: git working tree vs HEAD (`git diff HEAD`),
  covering staged + unstaged tracked changes; untracked files are
  named in a note, never silently included. `--diff -` reads stdin.
- Default out dir: current directory. The project tree is never written.
- Exit codes: 0 straightforward / needs-a-look, 1 needs-attention,
  2 could-not-review (empty or unparseable diff, unreadable diff file).

Outputs: REVIEW.md (plain English, template prose over counted facts)
and review.json (same facts machine-readable) - generated from one
report dict, so the numbers a human reads are the numbers a machine
consumes.

Per file: status, additions/deletions, hunks, binary flag, symbols
touched (added / removed / modified). Python symbols exact via ast on
the file on disk (definition ranges intersect added lines) plus
definition patterns over deleted lines; other languages parser-lite
line patterns, method labelled per file in both outputs.

Dependents: a deliberately simple ONE-HOP import scan
(dependents.py): Python import/from lines and JS/TS relative imports
resolved against the importer, skipping .git/caches/vendored trees.
Only project files NOT in the diff are listed. The report states it is
not Scope's call graph and not a complete blast radius.

Risk rules (risks.py, thresholds are named constants printed in
context): TEST-EDIT (deleted test file is high), CONFIG, DEPENDENCY
(manifests/lockfiles), SECRET-PATH, SECRET-SHAPED-LINE (path + line +
type only; the value is never copied into any output - verified),
LARGE-DELETION (100 lines in one file / 300 total / whole file
deleted), SYMBOL-REMOVED, MANY-DEPENDENTS (5+), BINARY,
NO-TEST-IN-DIFF (info), VERIFY-FAILED (only when a supplied Verify
report's exit code is non-zero).

Verdict derivation is a stated rule: any high flag = needs-attention,
any medium = needs-a-look, otherwise straightforward. No LLM, no
invented causes: if the inputs do not say why a change was made, the
review does not say.

Optional inputs are cited, never faked: a supplied verify-report.json
contributes verdict / exit code / hard+soft gap counts / post verdict
+ test status; a supplied Scope pack contributes the risk reasons
recorded in its scope.json (pack dir or scope.json path both work).
Absent inputs are stated in plain words in REVIEW.md. Supplied but
unreadable inputs are named as unreadable in notes.

MCP: stdio JSON-RPC server, one tool `review_diff`, capped risk list
(50), no diff text or file bodies, same pattern as Verify/Scope.

## Files

- PLAN.md, pyproject.toml (ghostreview 0.1.0, zero dependencies,
  console script `ghostreview = ghostreview.cli:main`)
- src/ghostreview/: __init__.py, __main__.py, cli.py, core.py,
  diffparse.py (unified diff parser, git-header and header-less),
  symbols.py, dependents.py, risks.py, inputs.py (git diff sources,
  Verify/Scope readers), reports.py (REVIEW.md + review.json),
  mcp_server.py

## Smoke tests run by Agent A (fixture project in /tmp, since removed
from the deliverable tree)

- Mixed diff (modify a.py removing `main` and adding `extra`, edit
  tests/test_a.py, add a file with a secret-shaped line): verdict
  needs-attention, exit 1; dependents correctly found b.py importing
  a.py; SYMBOL-REMOVED `main`, TEST-EDIT, SECRET-SHAPED-LINE all
  flagged; the secret value appears NOWHERE in REVIEW.md or
  review.json (grep count 0 in both).
- With --verify-report and --scope-pack fixtures: both cited in
  REVIEW.md, Verify verdict/gaps/post outcome quoted, both Scope risk
  reasons quoted.
- Empty diff: could-not-review, exit 2, never a clean verdict.
- Working-tree default (no --diff): reviewed staged + unstaged changes
  vs HEAD; the dependent b.py correctly dropped from the dependent
  list once b.py itself was in the diff.
- MCP: initialize + tools/call review_diff answered over stdio.
- pip install of the package into a target dir succeeded and the
  installed copy runs (`python -m ghostreview review ...`).

## Cross-check with Agent B's suite (landed in parallel)

Ran B's tests against this core: tests/test_cli_review.py +
tests/test_fixtures_static.py = 41 passed, 1 failed; tests/test_mcp.py
= 1 passed. The single failure is inside B's own fixture checks, not
the core: TestReportFixtures.test_verify_report_fixture_shape expects
B's fixture verify-report.json gaps[0] to have a "class" key, but B's
fixture (and real GhostVerify output) uses symbol/file/reason/via with
no "class" key. Flagged here for the parent; fixing it is a one-line
change on B's side (fixture or expectation), core needs no change.
Note: a bare `pytest tests` run also collects B's fixture project file
tests/fixtures/sample_project/tests/test_pricing.py as a test module
and errors on its intentional `from pricing import` - B may want a
conftest collect-ignore for fixtures; not a core issue.

## Honest limits (also printed in every REVIEW.md)

- Non-Python symbol detection is line-pattern level; a change deep
  inside a long non-Python function may be attributed to no symbol.
- The dependent scan is one hop and import-shaped only; dynamic and
  string-based references are missed by design in v0.1.
- Python dependent matching resolves full dotted paths and
  same-directory sibling imports; `__init__.py` package imports are
  matched by package name spelling only.
- The verdict is a summary of flagged rules, not a safety guarantee
  and not a merge decision. Copy says so in PLAN.md and in every report.

## Gates held

Local only, no network calls anywhere in src/, no push, no publish,
no announcements, no spend. No files outside ~/workspace/ghostreview/
were created or modified (smoke fixtures lived in /tmp; the pip
build/ byproduct in the repo root was removed).
