# GhostHandoff v0.1 - Implementation Record (Agent A, core)

Built Oct 14, 2026. Ownership held: PLAN.md, src/**, pyproject.toml, this file.
tests/**, README.md, examples/** are Agent B's and were not edited.

## What was delivered

- [PLAN.md](PLAN.md) - full plan in GhostSlice format (why this name, problem,
  position in the stack, pairing contract, MVP, out of scope, build estimate,
  pricing draft marked not public and not decided, verification bar, risks,
  next gate). No em dashes anywhere in the plan or the source.
- [pyproject.toml](pyproject.toml) - ghosthandoff 0.1.0, zero dependencies,
  console script `ghosthandoff`, src layout, Python >= 3.10.
- `src/ghosthandoff/gitfacts.py` - every git fact. Only read-only subcommands
  are reachable (rev-parse, status, log, diff, ls-files, stash list) behind an
  allowlist in `run_git`, and every call passes `--no-optional-locks` with
  `GIT_OPTIONAL_LOCKS=0` so git does not even refresh the index while
  reporting. Ahead/behind is counted with `log` ranges to keep the allowlist
  that small. Session window: default last 12 hours, or `--since` as a
  duration (`2h`, `90m`, `3d`), an ISO date/time, or a git ref (`ref..HEAD`).
  Uncommitted changes are always in the session regardless of window.
- `src/ghosthandoff/scan.py` - TODO/FIXME/XXX/HACK marker scan (text files up
  to 512 KB, binary skipped by NUL check, totals counted past the list cap)
  and verification-report discovery: `verify-report.json` (verdict field
  extracted), `VERIFY.md` (first line), Bench report names, the GhostSlice
  history ledger tail, `.pytest_cache` lastfailed count, and GhostSlice
  bundle folders (any `manifest.json` in the top two levels).
- `src/ghosthandoff/pack.py` - open-loop derivation and next-step drafting.
  Both are fixed templates over the measured facts; every loop and step
  carries its source. HANDOFF.md and handoff.json render from the same dict,
  so their numbers cannot disagree. If no loops exist, the pack says so and
  the next-steps list is empty. Nothing is invented.
- `src/ghosthandoff/redact.py` - secret-shape redaction applied to every
  quoted line (marker text, commit subjects, stash messages, report
  excerpts): AKIA / ghp_ / gho_ / github_pat_ / sk- / xox* shapes, bearer
  tokens, and credential-named `key = value` pairs.
- `src/ghosthandoff/cli.py` - `pack`, `show`, `mcp`. Exit codes: 0 = pack
  built (a non-git project still builds, git section marked unavailable),
  2 = could not build/read. Re-running into an existing pack directory
  refuses (exit 2) unless `--force`; only the two pack files are ever
  written, only in the output directory (default `./handoff-out` under the
  caller's cwd, never inside the described project by default).
- `src/ghosthandoff/mcp_server.py` - stdio JSON-RPC, tools `build_handoff`
  and `read_handoff`, summary payloads capped, HANDOFF.md capped at 8000
  chars, no project file bodies ever returned.

Hard rules verified in the code itself: there is no commit, push, send, or
edit path for the described project anywhere; no project code is executed
(no test runner, no build hook); no network imports exist. Import audit:
stdlib only (argparse, json, os, re, subprocess, sys, datetime).

## Smoke and verification results (all run by Agent A on the built core)

- Fixture repo (2 commits in window, 1 unstaged edit, 2 untracked files,
  1 stash entry, 3 markers, a failing verify-report.json):
  pack reports 2 commits, 4 files touched, 3 markers, 1 report, 5 open
  loops, 6 drafted next steps. The loops are exactly the planted facts.
- Read-only proof: `git status --porcelain` output and sha256 of every
  project file were byte-identical before and after the pack run, and
  still identical after every later run in this session.
- Redaction proof: a planted `ghp_...` token inside a TODO line appears
  0 times in both HANDOFF.md and handoff.json; it is replaced with
  `[redacted-secret-shape]`.
- Non-git folder: pack builds, exit 0, git section marked unavailable,
  marker still found.
- Clean repo: 0 loops, 0 steps; HANDOFF.md states "None found in the repo
  facts" and "No next steps were derivable from repo facts."
- Refusal paths: existing pack without `--force` exits 2; missing project
  path exits 2; `--force` overwrite succeeds.
- MCP round trip: initialize answers with serverInfo ghosthandoff 0.1.0,
  tools/list returns both tools, tools/call build_handoff and read_handoff
  return the fixture pack correctly.
- Real project: a pack of GhostSlice itself built cleanly (10 commits in
  the default window, 75 files touched, ledger + pytest-lastfailed reports
  found, loops for untracked files and recorded test failures). HANDOFF.md
  numbers cross-checked against handoff.json from the same run: agreement
  confirmed programmatically.
- Fresh-venv `pip install .` verified: the installed `ghosthandoff`
  console script reports 0.1.0 and reproduces the fixture pack exactly.
- Agent B's independently written suite against this core: **29 passed,
  0 failed** (final run; B aligned the suite to the landed CLI while both
  agents worked, first combined run mid-alignment showed transient
  failures that were gone on re-run without core changes).

## Known limits (honest)

- "This session" is a heuristic window printed on the pack's face; git has
  no session boundary. Commits just outside the window are invisible.
- Marker scan false positives are expected: markers in docs, fixtures and
  vendored text match. File and line are always given so a reader can
  judge; totals count everything matched.
- Report discovery is by known file names and shapes only (root level for
  verify/bench reports; top two levels for Slice bundles). Verification
  recorded anywhere else is missed and the pack's coverage note says so.
- Ahead/behind needs an upstream; without one the pack says "none
  recorded" rather than guessing.
- Porcelain rename handling in -z mode consumes the source-path record;
  exotic path characters are decoded with replacement, so a name can
  display imperfectly in the pack (the counts stay right).
- The pack goes stale the moment it is written. It is a stop-time
  snapshot, not a live view; live staleness is GhostWatch's job.
