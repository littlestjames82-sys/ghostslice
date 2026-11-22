# GhostConsole Agent B report: tests, README, examples

Ownership respected: only `tests/**`, `README.md`, `examples/**`, and
this file were written. No edits to `src/**`, `pyproject.toml`, or
`PLAN.md`.

## Final result against the real core

`python3 -m pytest tests -q` in `~/workspace/ghostconsole/`:
**18 passed, 0 failed**, confirmed on three consecutive full runs.
(The suite needs pytest; it uses pytest fixtures throughout.)

Tests discover the CLI via `GHOSTCONSOLE_CMD`, then `ghostconsole` on
PATH, then `python -m ghostconsole` with `PYTHONPATH=src`, and skip
cleanly when none is discoverable. All runs above used the third route
against Agent A's core; `pip install .` was not run by me.

## What the suite pins

- `tests/test_fixtures.py` (3 tests, no CLI needed): the fixture report
  trees carry the exact fields the plan's adapters read, in the shapes
  the sibling tools actually write (Slice ledger line and bundle
  manifest, Verify history line and verify-report.json, Bench report,
  Scope pack, Ledger report, Watch report, Approve store).
- `tests/test_columns.py` (3): the plan's fixture-board bar. One
  project per state lands in the right column (healthy Verified,
  failed-Verify Attention, Watch-stale Stale, empty Stale), placement
  checked structurally by section and card position in the HTML;
  attention-beats-stale precedence; the `--json` model agrees with the
  HTML classification.
- `tests/test_cli_build.py` (7): missing-tool bar (bare project,
  complete board, at least 7 "no report found" rows, exit 0);
  read-only bar (project tree hashes identical before and after a
  build); `--root` mode; `summary` text and `--json` parity; the
  stale window (74-day-old evidence is Stale by default, Verified with
  `--stale-days 120`); default output name `ghostconsole.html`.
- `tests/test_safety.py` (5): offline bar (no `http://`, no
  `https://`, no `<script`, no `<link>` / `<iframe>` / external `src=`
  in the output); hostile-content bar (script, img-onerror, and URL
  payloads planted in Verify and Scope report files never reach the
  board raw, and the board still completes); numbers exact (the
  fixture figures 123456 / 45678 Slice tokens, 3 Verify hard gaps, 2
  pending approvals, 5 Bench tasks appear on the board, accepting the
  core's thousands-separated rendering); unreadable report bar (a
  corrupt `scope.json` renders an unreadable-labelled row, the project
  lands in Attention, exit 0); report path shown on the card.

## Defects found

No core defects. Both failures seen during the build were bugs in my
own test files, fixed in my files only:

1. First run against the landed core: 16 passed, 2 failed. My
   "healthy" fixture reused the shared Bench fixture, which contains
   1 failing task, so the core correctly classified the project as
   Attention ("bench run fixture-run-1: 1 failing task(s)" was printed
   as the column reason). The core was right; the fixture was wrong.
   Fixed by parametrizing the Bench fixture's failure count and giving
   the healthy project a clean run.
2. Second run: 17 passed, 1 failed. My column locator matched bare
   words, and the word "attention" appears in the board's stylesheet
   before any section, so a project literally named "attention" broke
   placement detection. Rewrote the locator to use structural markup
   (`<section class="col X">` and the card `<h3>`), which is also a
   stronger test.

Core behaviour observed and matching the plan, worth recording: token
totals render thousands-separated ("123,456 -> 45,678"); timestamps a
format does not carry are labelled "(mtime)" on the row; a corrupt
report produces "[unreadable] GhostScope: pack unreadable
(JSONDecodeError: ...)" and Attention placement; every card prints its
"Why here:" rule line.

## Examples

`examples/fixture_reports/` holds the four fixture projects (verified,
attention, stale, empty) as static files in the real sibling shapes,
and `examples/board.html` is the board rendered from them by the real
CLI: 4 projects, 1 verified, 1 attention, 2 stale, and a grep of the
file finds no `http://`, `https://`, or `<script`.
`examples/run_demo.sh` regenerates it.

## Docs

`README.md`: plain-words install and use, the three columns and their
precedence, the trust properties (read-only, offline by construction,
escaping, honest mtime labelling, green is not a guarantee), the report
inventory with the bounded-search rules, and the limits stated
plainly, including that absence cannot distinguish "fine" from "never
checked" beyond the absent row. No em dashes in README or examples.
