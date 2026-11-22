# GhostConsole
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![CI](https://github.com/littlestjames82-sys/ghostconsole/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostconsole/actions/workflows/ci.yml)

One offline board for every Ghost tool report.

Every Ghost tool already writes its verdict down as a local file:
GhostSlice leaves a history ledger and bundle manifests, GhostVerify
leaves verdicts, GhostBench leaves run reports, GhostScope leaves
review packs, GhostLedger leaves cost reports, GhostWatch leaves
freshness verdicts, GhostApprove leaves a queue, GhostHandoff leaves
session packs, GhostLogs leaves incident packs, GhostDeps leaves
dependency manifests, GhostData leaves data packs. Until now, seeing
the whole picture meant opening a dozen files across a dozen folders.

GhostConsole reads those report files and renders one static HTML
board: three columns (Verified, Attention, Stale), one card per
project, one row per tool. It runs nothing, changes nothing, and
phones nowhere. It is a viewer, not a tool in the chain.

In short:

- **Input:** one or more project folders (or `--root` for a folder of
  projects).
- **Output:** one self-contained HTML file (`build`), or the same
  model as text or JSON in the terminal (`summary`, `--json`).
- **Effect on your projects:** none. GhostConsole is read-only; see
  "Trust, in plain words" below.

## Install

Requires Python 3.10 or newer. Zero dependencies: Python standard
library only.

```sh
pip install .
ghostconsole --help
```

Without installing, run it from a source checkout as a module:

```sh
PYTHONPATH=src python3 -m ghostconsole --help
```

## Quick start

```sh
# 1. Build a board for one project (writes ghostconsole.html)
ghostconsole build ~/work/app

# 2. Open the board in any browser; it works fully offline
# 3. Or read the same result in the terminal, without writing a file
ghostconsole summary ~/work/app
```

## Use

```sh
# One board for several projects
ghostconsole build ~/work/app ~/work/api -o board.html

# Every immediate subdirectory of a folder as a project
ghostconsole build --root ~/work -o board.html

# Same model in the terminal, or as JSON for other tools
ghostconsole summary ~/work/app
ghostconsole summary ~/work/app --json
ghostconsole build ~/work/app --json

# A shared GhostApprove store, shown as its own extra board entry
ghostconsole build ~/work/app --approve-store ~/work/.ghostapprove
```

| Option | Applies to | Meaning |
| --- | --- | --- |
| `PROJECT ...` | both | Project directories to read reports from. May be combined with `--root`; duplicates are read once. |
| `--root DIR` | both | Treat every immediate subdirectory of `DIR` as a project. Hidden directories are skipped. |
| `-o`, `--output FILE` | `build` only | Board file to write (default: `ghostconsole.html` in the current directory). Ignored when `--json` is given: JSON goes to stdout and no board file is written. |
| `--stale-days N` | both | How old (in days, default 7) the newest evidence may be before a project counts as stale. |
| `--approve-store DIR` | both | A shared GhostApprove store directory, shown as its own card in addition to any per-project stores. |
| `--json` | both | Print the board model as JSON to stdout instead of HTML or text. |
| `--version` | top level | Print the version and exit. |

Exit codes:

- `0`: a board or summary was produced. Missing reports are content
  ("no report found" rows), not errors, so an empty project still
  exits `0`.
- `2`: usage error: no projects given, `--root` or `--approve-store`
  is not a directory, or the output file could not be written.

## The columns

- **Attention**: a Verify verdict that failed, a Bench run with
  failing tasks, a Ledger loop warning, pending Approve requests, or
  a report that exists but cannot be read.
- **Stale**: a Watch verdict of stale or unknown, the newest evidence
  older than the stale window, or no reports at all.
- **Verified**: at least one report present, every present report ok,
  and the newest evidence inside the stale window.

A project's column is the worst of its rows: attention beats stale
beats verified. The reason for every placement is printed on the card.

Only live reports place a project. A report found under a test,
fixture, or example directory (`tests/`, `fixtures/`, `examples/`,
and kin) is material the project ships, not state the project
produced: its row is shown, labelled "(fixture/example report)", and
it never moves the project into any column, good or bad. A project
whose only reports are fixture material sits in Stale with the reason
stated on the card. Live reports always win over fixture ones for
the same tool.

Rows for the history-backed tools (Slice, Verify, Bench) also carry
a trend line when the tool's history file holds two or more readable
entries: how many entries were recorded, and how the latest compares
with the previous one (tokens saved for Slice, the verdict and how
many past verdicts needed attention for Verify, failing-task counts
for Bench, whose history records the count as `tasks_failed`). A
trend is context, never a verdict: it is built only from fields the
adapter already recognizes, and only the latest report places the
project, so a recovered tool is Verified even when older history
needed attention.

A tool that has not reported shows a quiet "no report found" row
(the Handoff, Logs, Deps, and Data rows name the artifact they look
for: "no handoff pack found", and so on). Absence is never an error
and never fails the build.

## Trust, in plain words

- **Read-only.** Console reads report files and writes exactly one
  file: the board. It never runs, schedules, or shells out to another
  Ghost tool, and it never edits a report.
- **Offline by construction.** The board is one HTML file with inline
  CSS, no JavaScript, and no external references of any kind. It works
  from a file share or a phone browser with no connection.
- **Nothing on the board can inject markup.** Every string that comes
  from a report file is HTML-escaped at render time. A project whose
  reports contain HTML or script-shaped text shows that text as text.
- **Honest times.** Where a report format carries no timestamp, the
  board uses the file's modification time and labels it as mtime. It
  never presents an mtime as a run time.
- **A green board is not a guarantee.** It means the latest reports on
  disk say ok. The board says so itself, in its footer.

## Which reports it reads

One row per tool, per project:

| Row | Files looked for (per project) |
| --- | --- |
| Slice | `.ghostslice-history.jsonl`, else the newest bundle `manifest.json` |
| Verify | `verify-report.json`, else `.ghostverify-history.jsonl` |
| Bench | `bench-report.json`, else `.ghostbench-history.jsonl` |
| Workflow | Newest `.ghostworkflow/<run-id>/workflow-report.json` |
| Scope | Newest `scope.json` |
| Ledger | `ledger-report.json`, else `.ghostledger.jsonl` |
| Watch | Newest `watch-report.json` |
| Approve | `.ghostapprove/` store (project root or nested), or `--approve-store` |
| Handoff | Newest `handoff.json` |
| Logs | A `manifest.json` with the GhostLogs shape, beside its `INCIDENT.md` |
| Deps | Newest `deps-manifest.json` |
| Data | A `manifest.json` with the GhostData shape, beside its `PROMPT.md` |

In detail: Slice (`.ghostslice-history.jsonl`, newest bundle
`manifest.json`), Verify (`.ghostverify-history.jsonl`,
`verify-report.json`), Bench (`.ghostbench-history.jsonl`,
`bench-report.json`), Workflow (newest
`.ghostworkflow/<run-id>/workflow-report.json`: the run's verdict,
its per-step outcomes, and its tree hash when it states one; the row
names the `board.html` the run rendered beside its report), Scope
(newest `scope.json`), Ledger
(`ledger-report.json`, else `.ghostledger.jsonl`), Watch (newest
`watch-report.json`), Approve (`.ghostapprove/` store, root or
nested), Handoff (newest `handoff.json`: session state, open loop and
next step counts; a pack is a snapshot, not a verdict, so it never
drives Attention on its own), Logs (a `manifest.json` identified by
the GhostLogs shape beside its `INCIDENT.md`: line accounting,
budget, error windows, redactions; a pack that shipped over budget or
whose counts do not reconcile is Attention), Deps (newest
`deps-manifest.json`: declared vs imported counts; imported but not
declared is Attention, declared but not imported is stated only,
which is GhostDeps' own "a lead, not a verdict"), Data (a
`manifest.json` identified by the GhostData shape beside its
`PROMPT.md`: rows parsed, columns, redacted columns; malformed
source rows are Attention). Logs and Data manifests share the bare
name `manifest.json` with Slice bundles, so they are claimed only by
their parsed shape; a corrupt `manifest.json` is claimed only when
the pack's companion file sits beside it. Anything that does not
match a documented shape is not guessed at. Searches are
bounded (depth 4, `.git` / `node_modules` / virtualenvs / caches
skipped, symlinks not followed, files over 5 MB not parsed), and the
card names the exact file used, so a wrong pick is visible.

## Troubleshooting

- **A project I expected in Verified is in Stale.** The reason is
  printed on its card ("Why here: ..."). The usual causes are: no
  live reports were found, a Watch verdict of stale or unknown, or
  the newest live evidence is older than `--stale-days` (default 7).
  Widen the window with `--stale-days N` if the reports are simply
  old but still the ones you trust.
- **A project is in Attention and I do not see a failure.** Look for
  a row labelled "unreadable": a report that exists but cannot be
  parsed is an Attention row by design. It is never dropped, and the
  row names the exact file, so you can open that file and fix or
  regenerate it with the owning tool.
- **A tool row says "no report found" but the tool did run.** The
  search is bounded: depth 4, files over 5 MB are not parsed, and
  `.git`, `node_modules`, virtualenvs, and caches are skipped (see
  "Which reports it reads"). A report outside those bounds will not
  be found. The card names the file that *was* used for each row.
- **A report is shown but labelled "(fixture/example report)".**
  It was found under a `tests/`, `fixtures/`, `examples/`, or similar
  directory, so it is material the project ships, not live state.
  Fixture rows never move a project into any column; run the owning
  tool in the project itself to produce a live report.
- **An mtime is shown instead of a run time.** That report format
  carries no timestamp of its own. The board labels the file's
  modification time as "mtime" and never presents it as a run time.

## Limits, stated plainly

- Console reports what reports say. A tool that never ran leaves no
  evidence, and the board cannot tell "fine" from "never checked"
  beyond showing the absent row.
- Report shapes are young and may drift. A live report that cannot be
  parsed shows as "unreadable" on its row (and puts the project in
  Attention) instead of breaking the board; a fixture/example report
  that cannot be parsed is labelled the same way but, like all
  fixture material, does not place the project. Unrecognized verdict
  wording is noted on the row rather than guessed at.
- A report buried deeper than the bounded search, or inside a skipped
  directory, will not be found. The card shows which file was used.
- v0.1 is a static file. There is no server, no live refresh, and no
  acting from the board: no approve buttons, no re-run links. Paths
  are text, not actions.

## Examples and licence

`examples/` holds a four-project fixture report set (one per board
state) and the board rendered from it; see `examples/README.md` and
`examples/run_demo.sh` to regenerate it. Licence: MIT (see
`LICENSE`).

---
<!-- ghost-studio-footer -->
## More from Ghost Developer Studio

Ghost Developer Studio builds developer tools, AI-agent safety software, and practical apps, and sells by showing working software, not slide decks.

- [Roadmap board](https://github.com/littlestjames82-sys/ghost-roadmaps): where every studio product stands
- [Agent Seatbelt](https://github.com/littlestjames82-sys/agent-seatbelt): deterministic guardrails for AI coding agents
- [Ghost Hands](https://github.com/littlestjames82-sys/ghost-hands): governed, recorded, replayable agent hands
- [GhostSlice](https://github.com/littlestjames82-sys/ghostslice): agent context and prompt optimizer
- [GhostIDE](https://github.com/littlestjames82-sys/ghostide-android): fully offline AI code editor for Android
- [All studio projects](https://github.com/littlestjames82-sys?tab=repositories)
