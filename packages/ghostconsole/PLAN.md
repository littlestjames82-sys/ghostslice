# GhostConsole - One Offline Board for Every Ghost Tool Report
Working name, prepared Oct 14, 2026. Paired tool #29 for GhostSlice, Wave 4.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostConsole: plain job, plain name. A console is where you look to see the state of the whole system at a glance. This one shows the state of the Ghost tools' own reports.
- Checked against the family: Slice has a live dashboard for one running session; Console is not that. Console is a static, offline board built from report files already on disk, across as many projects as the user points it at. No claim of a live product search yet. Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostBoard (accurate but generic, and Ghost Bridge already uses board language for its queue), GhostPanel (implies a live UI surface, which v0.1 is not).

## The problem
Every Ghost tool already writes its verdict down as a local file, and nobody reads them together:

- GhostSlice leaves `.ghostslice-history.jsonl` and bundle manifests per project.
- GhostVerify leaves `verify-report.json` next to bundles and `.ghostverify-history.jsonl` per project.
- GhostBench leaves `bench-report.json` per run and `.ghostbench-history.jsonl`.
- GhostScope leaves a pack (`scope.json` + `REVIEW.md`).
- GhostLedger leaves `ledger-report.json` + `LEDGER.md` and flags loop warnings.
- GhostWatch leaves `watch-report.json` with a fresh / stale / unknown verdict per bundle.
- GhostApprove leaves a queue store (`.ghostapprove/` with `requests/` and `ledger.jsonl`).

To answer "is everything fine, and what needs my eyes?" today, the developer opens a dozen files across a dozen project folders, or more likely does not check at all, and finds out about the stale bundle, the failed bench run, or the three pending approvals from a wasted agent run instead. There is no single page that aggregates what the tools already reported.

## Position in the Ghost stack
- GhostSlice governs what an agent READS.
- The companion tools each govern one question: was it enough (Verify), what did it cost (Ledger), is it still fresh (Watch), what changed (Scope), what is waiting on a human (Approve), does it hold up under test (Bench).
- GhostConsole governs none of those. It READS the answers and puts them on one board. It is a viewer, not a tool in the chain.
- Agent Seatbelt governs what an agent DOES. Ghost Hands is the governed browser body.

Story: tools run and write reports -> Console renders the board -> the human sees verified / attention / stale at a glance -> the human runs the owning tool to act. Console itself never acts.
No overlap: Slice's dashboard is a live session view for one project. Console is a static file built from saved reports across projects, and it starts no server.

## How it pairs with the suite, concretely
Read-only by construction. Console imports no sibling tool, executes no sibling tool, and opens no sibling's source files. It reads only published report artifacts, by file name and documented shape:

- Slice: `<project>/.ghostslice-history.jsonl` (latest export line) and the newest bundle `manifest.json` found under the project (bounded search).
- Verify: `<project>/.ghostverify-history.jsonl` (latest verdict line) and the newest `verify-report.json` under the project.
- Bench: `<project>/.ghostbench-history.jsonl` (latest run line) and the newest `bench-report.json` under the project.
- Scope: the newest `scope.json` under the project.
- Ledger: `<project>/ledger-report.json` when present, else `<project>/.ghostledger.jsonl` counted directly.
- Watch: the newest `watch-report.json` under the project.
- Approve: `<project>/.ghostapprove/` store (`requests/*.json` minus ids decided in `ledger.jsonl`) plus an optional `--approve-store <path>` for a shared store.

Integration contract:
- Input: one or more project paths, or `--root <dir>` to take every immediate subdirectory as a project. Optional `--stale-days N` (default 7) and `--approve-store <path>`.
- Output: one self-contained HTML file (inline CSS, no JavaScript, no external assets) written to `-o` (default `ghostconsole.html` in the current directory), plus a text summary on stdout. A `--json` summary mode prints the collected board model for other tools.
- Adapters are tolerant by design: a missing tool means its row says "no report found" and nothing else changes. A present but unreadable or unrecognized report is shown as such, never silently dropped and never a crash.
- Every string that comes from a file is HTML-escaped at render time. Project content can never inject markup into the board.

## MVP (v0.1) - static HTML board, kanban columns
Rationale: same as the rest of the suite. A static file proves the aggregation on real report files in days, opens anywhere (including a phone browser from a file share), and has no server to secure. A live or served board is a later gate.

1. Collect: `ghostconsole build <project>... [-o board.html] [--root <dir>] [--stale-days N] [--approve-store <path>]`
   - One adapter per tool above. Each adapter returns a section: tool name, state (ok / attention / stale / absent / unreadable), a one-line summary built only from fields it recognizes, the report path, and the report time (embedded timestamp when the format has one, else file mtime).
   - Searches under a project are bounded: maximum depth 4, `.git`, `node_modules`, virtualenvs and caches skipped, symlinks not followed, files over 5 MB not parsed. The newest matching report by mtime wins.
   - Console's own output file is excluded when it lands inside a scanned tree.

2. Classify into three columns (Ryan's board shape):
   - Attention: a Verify verdict that failed, a Bench run with failing tasks, a Ledger loop warning, one or more pending Approve requests, or a report that exists but cannot be read.
   - Stale: a Watch verdict of stale or unknown, or the newest evidence for the project is older than `--stale-days`, or the project has no reports at all.
   - Verified: at least one present section, every present section ok, and the newest evidence inside the stale window.
   - A project's column is the worst of its sections (attention beats stale beats verified). The rule for every placement is printed on the card, so the board never asks to be trusted blindly.

3. Render: one HTML file.
   - Header: generated-at time, project count, per-column counts, stale window used.
   - Three columns of project cards. Each card lists one row per tool: status chip, one-line summary, report age, and the report path. Absent tools show as a quiet "no report found" row.
   - Inline CSS only, no JavaScript, no fonts or assets loaded from anywhere. The file works offline forever and can be attached or archived as evidence of state at a point in time.
   - All file-derived text escaped with `html.escape`. There is no raw-HTML path in the renderer.

4. Text summary: `ghostconsole summary <project>...` prints the same model as plain text (columns, per-tool rows), for terminal use and for tests. `--json` on either command prints the board model as JSON.

## Out of scope for v0.1
- Running, scheduling, or shelling out to any other Ghost tool. Console reads files; if a report is old, the board says so and the human re-runs the owning tool.
- A server, a live-refresh page, accounts, or anything network-shaped. The output is a file.
- Acting on what the board shows: no approving from the board, no re-export buttons, no links that trigger anything. Paths are text, not actions.
- Editing, moving, or cleaning up report files. Console writes exactly one file: its board (and nothing into any project tree unless the user points `-o` there).
- Reading report formats beyond the seven adapters above. New tools join by adding an adapter, not by scraping screens.

## Build estimate
- Board model + classification rules: 1 day
- Seven tolerant adapters with bounded search: 2-3 days
- HTML renderer (escaping, columns, chips) + text/JSON summary: 1-2 days
- Tests (fixture report trees per tool, missing-tool trees, hostile content escaping, stale/attention classification), README, demo board built from the suite's own workspace projects: 1-2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through. The adapters are the part most likely to need adjustment, because each sibling report shape is young and may drift; tolerance and honest "shape not recognized" rows are the mitigation, not a blocker.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Verify / the rest of the suite.
- Paid candidate later only: a team board pack (multi-workspace rollups, scheduled board builds inside a CI product). Do not build a paid layer before a free launch validates demand.

## Verification bar
- Fixture board: a tree with one project per state (verified, attention via a failed Verify verdict, stale via a Watch stale verdict, empty project) must place all four in the right columns with the rule named on each card.
- Missing-tool bar: a bare project with no Ghost artifacts at all renders a complete board with "no report found" rows and exit 0. Absence is never an error.
- Hostile-content bar: a report containing HTML and script-shaped strings renders those strings as visible text. The output contains no unescaped file-derived markup and no `<script` of any origin.
- Self bar: a board built over the suite's own workspace projects (ghostslice, ghostverify, ghostbench, and neighbours) matches a hand count of the reports actually on disk.
- Offline bar: the generated file references no external URL. Grep for `http://` and `https://` in the output returns nothing except, if present at all, an XML namespace string in an SVG, which v0.1 does not use.

## Risks / honest notes
- Sibling report shapes are young (several tools were built the same week). Adapters read defensively and label what they could not recognize; a shape drift degrades a row to "report found, shape not recognized" instead of breaking the board. That is the honest failure mode, and it is visible on the board itself.
- Report times are only as good as what the formats carry: where a format has no timestamp, Console uses file mtime and labels it as mtime, never presents it as a run time.
- A green board means "the latest reports say ok," not "the projects are healthy." Copy on the board says exactly that: latest report state, not a live guarantee.
- Bounded search can miss a report buried deeper than depth 4 or inside a skipped directory. The card shows which file was used, so a wrong pick is visible rather than silent.

## Next gate
Ryan's go on: (1) GhostConsole as working name, (2) static HTML file first, no server in v0.1, (3) the three-column classification rules above (attention / stale / verified with the stated precedence), (4) the seven v0.1 adapters (Slice, Verify, Bench, Scope, Ledger, Watch, Approve).
