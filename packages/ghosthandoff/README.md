# GhostHandoff
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghosthandoff/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghosthandoff/actions/workflows/ci.yml/actions)

A session handoff pack for GhostSlice projects. When a working
session stops, GhostHandoff writes one small pack that says where
things stand: what branch, what changed, what is still open, and
what the next session should probably do first. The next agent or
person starts from the pack instead of re-reading the whole repo.

The pack is drafted from repo facts only. Every fact in it names
its source. Nothing in it is guessed, summarised by a model, or
carried out for you: the tool is propose-only, and it never commits,
pushes, sends, or edits anything in the project it describes.

> **In one line:** `ghosthandoff pack <project>` reads git state,
> recent commits, report files, and TODO markers, then writes
> `HANDOFF.md` + `handoff.json` somewhere else. Your project is
> left byte-identical.

## 30-second start

```sh
# From a checkout of this repo, no install needed:
PYTHONPATH=src python3 -m ghosthandoff pack /path/to/project

# Or, once installed (pip install / pipx):
ghosthandoff pack /path/to/project
ghosthandoff show ./handoff-out
```

That first command creates `./handoff-out/` under your *current*
directory (not inside the project) with two files:

| File | For | Contains |
| --- | --- | --- |
| `HANDOFF.md` | People and the next agent | The readable handoff: state, changes, verification, open loops, next steps |
| `handoff.json` | Tools and scripts | The exact same facts, machine readable. Numbers in the two files cannot disagree: both are rendered from one dict |

Then hand `HANDOFF.md` to whoever or whatever picks the work up
next. That is the whole workflow.

## Commands

```sh
ghosthandoff pack <project> [-o <dir>] [--since <when>] [--base <ref>] [--force] [--json]
ghosthandoff show <pack-dir>
ghosthandoff mcp
ghosthandoff --help            # top-level help
ghosthandoff pack --help       # pack options in detail
```

- **`pack`** builds a pack. Default output is `./handoff-out`
  under your current directory, never inside the project unless
  you point `-o` there yourself. If `HANDOFF.md` or `handoff.json`
  already exists in the output directory, `pack` refuses and exits
  2; pass `--force` to overwrite just those two files.
  `--json` prints the run summary as JSON instead of plain text.
- **`show <pack-dir>`** prints a pack's `HANDOFF.md` to stdout, so
  you can read a handoff without opening the file by hand.
- **`mcp`** serves two tools over stdio for MCP clients:
  `build_handoff` (same as `pack`, returns capped summary counts
  plus the pack paths) and `read_handoff` (returns a pack's
  `HANDOFF.md`, capped at 8,000 characters). Local only, no network.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Pack built, or pack shown. A section can still be *degraded and labelled*: for example, a project that is not a git repo still gets a pack with the git section marked unavailable. |
| `2` | Pack could not be built or read: the project path is missing or unreadable, the output pack already exists without `--force`, or `show` found no `HANDOFF.md`. |

### Choosing the session window: `--since`

Git does not record when a "session" started, so the window is an
explicit, printed approximation. Uncommitted changes are *always*
included, whatever window you pick.

| `--since` value | Meaning | Example |
| --- | --- | --- |
| *(omitted)* | Last 12 hours, plus all uncommitted changes | `ghosthandoff pack .` |
| Duration | Last `N` minutes / hours / days | `--since 2h`, `--since 90m`, `--since 3d` |
| ISO date or datetime | Commits at or after that moment | `--since 2026-10-17`, `--since "2026-10-17 09:00"` |
| Git ref | Commits in `ref..HEAD` | `--since main`, `--since HEAD~5` |

`--base <ref>` is separate: it adds one extra line to the pack,
the diff stats for `base...HEAD`, so a reviewer can see the total
size of a branch against its base.

## What is in the pack

Every section below appears in both files. The right-hand column is
the source the pack itself prints next to the fact, so a reader can
check any line in seconds.

| Pack section | Question it answers | Source named in the pack |
| --- | --- | --- |
| **State now** | Which branch and commit am I on, and how dirty is the tree? | `git status`, `git rev-parse`, stash list |
| **Changed this session** | What commits and file changes belong to this session? | `git log` inside the window, staged / unstaged diff stats |
| **Verification status** | What did the last check say, and how old is that claim? | The report file itself, with its path and modification time |
| **Open loops** | What is unfinished, unpushed, or failing? | Derived only from the facts above; each loop cites its fact |
| **Next steps** | What should the next session do first? | One templated draft per open loop, in a fixed priority order |
| **Markers** | Where are the TODO / FIXME / XXX / HACK markers? | Marker scan, with file, line, and code-vs-docs context |
| **Coverage and limits** | What might this pack have missed? | The tool's own stated caps and discovery rules |

In more detail:

- **State now.** Branch (or detached HEAD), short HEAD hash,
  upstream with ahead and behind counts, staged / unstaged /
  untracked file lists from git status, stash entries, and any
  in-progress git operation (merge, rebase, cherry-pick, revert,
  bisect) detected from git-dir marker files such as
  `.git/MERGE_HEAD`, with unmerged (conflicted) files listed
  separately instead of counted as staged or unstaged.
- **Changed this session.** Commits inside the session window,
  with hash, subject, author, and time, plus the files they
  touched, and working-tree diff stats for staged and unstaged
  changes separately. The window is printed on the pack. The
  default is the last 12 hours plus all uncommitted changes,
  because uncommitted work is part of the handoff no matter how
  old it is.
- **Verification status.** Report files the tool recognises
  (GhostVerify, GhostBench, GhostSlice ledger and bundles, pytest
  cache), each with its kind, path, modification time, and a short
  extract from the file itself: a verdict field, a first line, a
  failure count. A three-day-old report reads as three days old.
  Nothing is re-run to refresh it.
- **Open loops.** Only from the facts above: an in-progress git
  operation and its unmerged files, uncommitted files,
  unpushed commits, stash entries, TODO / FIXME / XXX / HACK
  markers in code files, a non-passing latest verdict, recorded
  test failures. Each loop names its source. (Markers found in
  documentation or fixture files are listed in the pack's Markers
  section, not counted as loops; see Honest limits.)
- **Next steps.** Short drafts generated from the open loops in a
  fixed priority order, each citing the fact it came from. If
  there are no loops, the pack says no next steps were derivable
  from repo facts. It never invents work.

### A tiny example

For a mid-session project the top of `HANDOFF.md` looks like this
(hashes and times vary; the shape does not):

```text
# Handoff: demo-project

Drafted by GhostHandoff 0.1.0 from repo facts at 2026-10-18T...
Propose-only: nothing was committed, sent, or changed in the
project. Every fact names its source. ...

## State now
- Branch: feature/handoff-fixture (HEAD 832f9d8)
- Upstream: none recorded
- Working tree: 1 staged, 1 unstaged, 3 untracked
- Stash: 1 entry

## Changed this session
Window: last 12 hours (default) plus all uncommitted changes
- Commits in window: 2
```

See `examples/` for a runnable walkthrough that builds exactly
this demo repo and packs it, step by step.

### Reading `handoff.json`

`handoff.json` has the same structure as the Markdown: top-level
keys `project`, `session_window`, `git`, `markers`, `reports`,
`open_loops`, `next_steps`, and `limits`, plus `tool`, `version`,
and `generated_at`. If you script against it, prefer those keys
over parsing `HANDOFF.md`. After a `pack` run the CLI summary (or
the `--json` summary) also reports `pack_markdown` and `pack_json`
paths, `commits_in_window`, `files_touched`, `markers`,
`reports_found`, `open_loops`, and `next_steps` counts.

## Safety, in plain words

This is the read-only guarantee, stated once and enforced in code
and in the test suite:

- **Read-only on your project.** Git is driven with read-only
  subcommands only (`rev-parse`, `status`, `log`, `diff`,
  `ls-files`, `stash list`) and optional locks disabled
  (`--no-optional-locks`, `GIT_OPTIONAL_LOCKS=0`), so git itself
  writes nothing back. The test suite hashes the described
  project's whole tree, `.git` included, before and after a pack
  run and requires the hashes to match exactly.
- **Propose-only.** There is no commit, push, send, or edit path
  anywhere in the tool. It writes the two pack files, only in the
  output directory. Next steps in the pack are drafts for the next
  session to confirm, never actions the tool took.
- **It never runs your code.** No tests, no builds, no scripts
  from the described project. Git read-only commands and file
  reads are the whole surface.
- **Secrets stay out.** Marker lines and report excerpts are
  quoted truncated, and pass through a secret-shape redaction pass
  before they are written.
- **Local only.** Python standard library only, no network, no
  accounts, no telemetry.

## Honest limits

- "This session" is a heuristic. Git does not record session
  boundaries, so the window is a stated approximation, never an
  exact measurement.
- Marker scans have false positives. A TODO inside docs or
  fixtures matches too, so the pack splits markers by context:
  markers in documentation or fixture files are listed with file
  and line and subtotalled, but only markers in code files count
  as open loops or generate next steps. The split is conservative
  (a docs directory, a fixture directory, or a documentation file
  extension), and every marker is still listed so a reader can
  judge. Lists are capped, and the pack says when a cap was hit,
  including when the scan's file list itself was capped.
- Report discovery works by known file names and shapes. A
  verification result stored anywhere else will be missed, and
  the pack's coverage note says so.
- Operation detection reads git-dir marker files, so a marker
  left behind by a crashed git process would read as an
  operation still in progress.
- A pack is a snapshot from the moment it was built. It carries
  its build time on its face and goes stale right after; use
  GhostWatch if you need live staleness tracking.
- GhostHandoff captures one session at stop time. It does not
  learn across sessions (that is GhostReplay) and it is not a
  first-session orientation pack (that is GhostPrimer).

## Common questions

**My project is not a git repo. Do I still get a pack?**
Yes, exit 0. The git section is marked unavailable, and marker and
report sections are still built from the files on disk.

**Why does the pack quote an old, failing report?**
Because that is what is on disk. GhostHandoff never re-runs tests
or verifiers to refresh a result; it quotes the recorded verdict
with its modification time so its age is visible. Re-running is
GhostVerify's job.

**The pack already exists and `pack` exits 2. What now?**
That is deliberate overwrite protection. Re-run with `--force` to
replace `HANDOFF.md` and `handoff.json` in that output directory,
or pick a different `-o` directory.

**Where should I put the pack?**
Anywhere except, by default, inside the project. The default
`./handoff-out` in your working directory, a scratch folder, or a
shared handoff folder all work; `show` only needs the directory
that contains `HANDOFF.md`.

## Development

Zero-dependency Python (stdlib only), Python 3.10+.

```sh
PYTHONPATH=src python3 -m ghosthandoff pack <project>
python3 -m pytest tests -q
```

See `examples/` for a walkthrough that builds a fixture repo in a
known mid-session state and packs it. See `PLAN.md` for the full
design and the verification bar the test suite pins.

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
