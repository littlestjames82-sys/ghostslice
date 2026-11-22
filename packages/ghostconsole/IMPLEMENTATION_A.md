# GhostConsole v0.1 - Implementation Notes (Agent A, core)

Built Oct 14, 2026 from PLAN.md (written first, same pass, in the
GhostSlice plan format). Ownership respected: PLAN.md, src/**,
pyproject.toml, and this file only. tests/**, README.md, examples/**
are Agent B's and were not edited.

## What was built

- `pyproject.toml`: ghostconsole 0.1.0, zero dependencies, console
  script `ghostconsole`, setuptools src layout matching the suite.
- `src/ghostconsole/model.py`: Section (one tool's latest word on one
  project) and ProjectBoard (sections + chosen column + the reason,
  always carried in the model so the board prints why each card sits
  where it sits). States: ok / attention / stale / absent / unreadable.
  Columns: verified / attention / stale.
- `src/ghostconsole/adapters.py`: one tolerant adapter per tool, plus
  shared IO. Adapters read published report artifacts only; no sibling
  tool is imported or executed.
  - GhostSlice: `<project>/.ghostslice-history.jsonl` latest line
    (kind, before/after/saved tokens), else the newest shape-validated
    bundle `manifest.json` under the project.
  - GhostVerify: newest `verify-report.json` (verdict + gap count +
    post/patch verdict), else `.ghostverify-history.jsonl` latest line.
  - GhostBench: newest `bench-report.json` (run id, task count,
    failing task count by status), else `.ghostbench-history.jsonl`.
  - GhostScope: newest `scope.json` (first recognizable file-count
    list or count, max risk when present). Informational only, never
    drives attention in v0.1.
  - GhostLedger: `<project>/ledger-report.json` (totals + loop
    warnings), else `.ghostledger.jsonl` counted directly. Loop
    warnings drive attention.
  - GhostWatch: newest `watch-report.json` (fresh is ok; stale and
    unknown are stale).
  - GhostApprove: `<project>/.ghostapprove/` store (requests/*.json
    minus ids decided in ledger.jsonl), plus `--approve-store <dir>`
    rendered as its own card. Pending requests drive attention; the
    pending summary names the risk values present.
- `src/ghostconsole/collect.py`: runs the adapters, computes the
  newest evidence time per project, classifies with the precedence
  attention > stale > verified. Age staleness uses the NEWEST section
  time, so one fresh report keeps a project verified even if older
  tools have gone quiet. No reports at all classifies as stale with
  reason "no reports found".
- `src/ghostconsole/render.py`: HTML (inline CSS, no JavaScript, no
  external references), plain text, and JSON renderings of the same
  model. Every file-derived string passes through `html.escape` at
  render time; there is no raw-HTML path.
- `src/ghostconsole/cli.py`: `build` (writes the HTML file, prints
  column counts) and `summary` (text to stdout), both with `--json`,
  `--root`, `--stale-days` (default 7), `--approve-store`. Exit 0 on
  success (absent reports are content, not errors), exit 2 on usage
  errors (no projects, bad --root / --approve-store, unwritable -o).

Safety bounds in the search: depth 4, 20,000 visited files per
filename search, `.git` / `node_modules` / venvs / caches skipped,
symlinks not followed or read, files over 5 MB not parsed.

## Verification (all run by Agent A against the built core)

Fixture battery (nine synthetic projects in /tmp, timestamps relative
to run time):
- verified project (fresh Slice export line 129,555 -> 45,770, Verify
  history "sufficient"): Verified column, both rows ok with ages.
- attention via Verify: nested `bundle/verify-report.json` with
  verdict "insufficient" and 2 gaps: Attention, reason names the
  verdict, summary shows the gap count.
- attention via Approve: 2 requests, 1 decided in ledger.jsonl:
  Attention, "1 pending of 2 request(s) (risk: high)".
- attention via Ledger: ledger-report.json with 1 loop warning:
  Attention, totals and the warning both shown.
- stale via Watch: `watch-report.json` verdict "stale" nested two
  levels deep: Stale, reason names the verdict.
- stale via age: only evidence a Slice export 30 days old: Stale,
  reason "newest report is 30 day(s) old (stale window 7 day(s))".
- empty project: Stale, "no reports found", all seven rows absent,
  exit 0.
- hostile project: verdict and run id fields carrying `<script>` and
  `<img onerror>` payloads, scope file name carrying `<b>` markup.
  Board output: zero `<script` occurrences, zero external URLs, the
  payloads present only in escaped form (`&lt;script&gt;...`). The
  scope file name is counted, never rendered, so it cannot appear at
  all.
- corrupt project: `verify-report.json` and `watch-report.json`
  containing invalid JSON: both rows UNREADABLE with the parse error
  named, project in Attention. (A report-shaped name that parses but
  lacks the tool's key fields is treated as a look-alike and skipped;
  a file that does not parse is reported unreadable. `manifest.json`
  is the deliberate exception: the name is generic across ecosystems,
  so Slice manifests are shape-validated only and never produce an
  unreadable row.)

CLI behaviour: no projects exits 2 with a clear message; a bad
--root exits 2; a nonexistent project path renders an Attention card
("project path is not a directory") instead of crashing; `--json`
emits the full board model; `--approve-store` on a store with one
critical pending request renders its own Attention card; `--version`
prints ghostconsole 0.1.0.

Install: fresh venv `pip install .` (with --no-build-isolation, the
sandbox cannot fetch a build backend; the venv was given system site
packages for setuptools) succeeds; the installed CLI reports 0.1.0
and builds a board.

Real-data check (verification bar, self board): board over the
suite's own repos (ghostslice, ghostverify, ghostbench, ghostscope,
ghostledger, ghostwatch, ghostapprove) matched a hand check of the
files on disk. ghostslice verified via its real history; ghostbench
landed in Attention because its newest on-disk bench report is the
examples sample run B, which genuinely contains a failing task (the
by-design adversarial case, hand-confirmed: adv-002 status fail).
ghostapprove showed no sections: its own repo holds no store at its
root, which is correct behaviour for a cwd-based store.

Cross-check: Agent B's independently written suite (tests/, 18 tests)
was run against this core after it landed: 18 passed, no core changes
needed.

## Known limits (honest)

- Verdict vocabularies are matched loosely (pass-like vs fail-like
  substrings, fail checked first). A sibling wording its verdict in a
  new way degrades to "verdict wording not recognized" shown verbatim
  on an ok row, never to a silent pass or a crash, but a fail worded
  without any known fail token would not drive attention. The verdict
  text itself is always on the card.
- Report shapes are young across the suite. Adapters claim only the
  fields they recognize; anything else degrades the summary to counts
  or "shape not recognized in detail", visibly, on the row.
- Approve stores are only looked for at a project root
  (`.ghostapprove/`) or via --approve-store. Stores nested inside
  test fixtures are not searched, by design.
- Where a format carries no timestamp, file mtime is used and the row
  labels it "(mtime)"; it is never presented as a run time.
- Bounded search can miss a report deeper than depth 4 or inside a
  skipped directory. The card names the file actually used, so a
  wrong pick is visible.
- A Slice bundle manifest is only used when no Slice history exists,
  and only if it shape-matches (files list plus totals/root keys), to
  avoid picking up unrelated manifest.json files.
- Bench history fallback reads a `failed` field when the history
  format carries one; if it does not, the row is a plain latest-run
  line with no failure claim.
- No MCP server in v0.1 (the plan does not call for one; the board is
  the surface, `--json` is the machine interface).

## Gates held
Stdlib only (argparse, dataclasses, datetime, html, json, os,
pathlib, sys), local only, no network code anywhere, no GitHub push,
no PyPI/publish, no announcements, no spend. Console executed no
other tool at any point, including during verification (all fixtures
were hand-written files).
