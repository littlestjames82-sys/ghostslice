# GhostReview
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostreview/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostreview/actions/workflows/ci.yml/actions)

**What did this change actually do, in plain English?**

The GhostSlice companions already answer the machine questions
about a change. GhostScope builds a change-centred review *pack*
to read. GhostVerify checks whether a slice was enough and
whether a patch holds. Neither writes the short human summary a
tired developer can act on in under a minute.

GhostReview is that translation, and only that translation. It
reads a git diff, plus a GhostVerify report and a GhostScope
pack *when you supply them*, and writes one plain-English
review: what changed, which symbols were touched, which project
files import a changed file, and what the explicit risk rules
flagged, with a verdict derived only from those flags.

Every sentence is template-generated from counted facts. No
LLM, no model calls, no invented causes: if the evidence does
not say why a change was made, the review does not say either.
The verdict is a summary, not a merge decision. GhostReview
approves nothing, merges nothing, and comments nowhere.

By Ghost Developer Studio. MIT core (see PLAN.md for the pricing
posture: free core, paid layer not decided). Zero dependencies:
Python standard library only, local-first, no network, no
telemetry. Static evidence only.

Position in the Ghost stack: GhostSlice governs what an agent
*reads*, GhostScope governs what a reviewer *reads* for a
change, GhostVerify governs whether a patch *holds*,
GhostReview governs the plain-English *summary*, Agent Seatbelt
governs what an agent *does*.

## Install

```bash
cd ghostreview
pip install .
ghostreview --help
```

Or run from a checkout without installing:

```bash
PYTHONPATH=src python3 -m ghostreview --help
```

Requires Python 3.10 or newer. Reviewing a working tree (instead
of a diff file) also requires `git` on PATH.

## Quickstart

```bash
# Review a diff file
ghostreview review ~/my-project --diff agent.diff -o /tmp/review-out
status=$?   # capture it now: running cat first would replace $?
            # 0 straightforward/needs-a-look, 1 needs-attention,
            # 2 could-not-review
cat /tmp/review-out/REVIEW.md
echo "exit: $status"

# Review your own uncommitted changes (git diff HEAD)
ghostreview review ~/my-project -o /tmp/review-out

# Cite the other tools when their reports exist
ghostreview review ~/my-project --diff agent.diff \
  --verify-report /tmp/bundle/verify-report.json \
  --scope-pack /tmp/review-pack \
  -o /tmp/review-out

# Preview without writing files, or print machine-readable JSON
# (handy in CI; combine --no-report with --json for JSON only)
ghostreview review ~/my-project --diff agent.diff --no-report
git diff HEAD | ghostreview review ~/my-project --diff - --no-report --json
```

### Choosing a diff source

Pick exactly one source per review:

| Source | Use it when |
|---|---|
| `--diff <file>` | You already saved a diff, for example an agent's patch. `--diff -` reads the diff from stdin instead. |
| *(no flag)* | You want your working tree against `HEAD`: staged and unstaged tracked changes together. Untracked files are listed as a note, never reviewed. |
| `--staged` | You want staged changes only (`git diff --cached`). |

The `<project>` argument is always the project root the diff
belongs to, whichever source you pick: symbols and dependents are
looked up there. The project tree is never modified.

A worked walkthrough lives in [`examples/`](examples/README.md).

## Commands

| Command | What it does |
|---|---|
| `ghostreview review <project> [--diff <file.diff> \| --staged] [--verify-report <path>] [--scope-pack <pack-dir\|scope.json>] [-o <out-dir>] [--json] [--no-report]` | Review a diff and write `REVIEW.md` + `review.json` to the output directory (default: the current directory). The default diff source is the git working tree against HEAD; `--staged` uses staged changes only; `--diff -` reads the diff from stdin. The project tree is never modified. |
| `ghostreview mcp` | Stdio MCP server (local only) exposing `review_diff` with a capped summary payload, no raw file bodies and no diff text. `review_diff` requires `project`; `diff`, `staged`, `verify_report`, and `scope_pack` are optional and mean the same as the CLI flags. |

## Verdict and exit codes

The verdict is derived only from the risk flags, by a stated
rule: any high flag means `needs-attention`, any medium flag
means `needs-a-look`, otherwise `straightforward`. An empty or
unparseable diff is `could-not-review`, never a clean verdict.

| Code | Meaning |
|---|---|
| 0 | `straightforward` or `needs-a-look` |
| 1 | `needs-attention` (at least one high flag) |
| 2 | `could-not-review`: empty/unparseable diff, or the diff file could not be read |

## Risk rules

Every flag cites its file, its rule name, and its reason. The
thresholds are constants in the core and are named in reports.

| Rule | Level | Fires when |
|---|---|---|
| `TEST-EDIT` | medium, high if a test file is deleted | A test file was added, edited, or deleted in the diff |
| `SECRET-PATH` | high | A changed path is secret-shaped (.env, credentials, key/cert material by name or extension). Path only, contents never shown |
| `SECRET-SHAPED-LINE` | high | An added line matches a secret shape (labelled assignment, token prefix, private-key header, password in a URL, context-gated AWS secret). Shapes mirror GhostSlice's canonical guard list; see SEAM_FIX_REPORT.md. Path + line + type only, the value is never copied into any output |
| `LARGE-DELETION` | high | One file loses 100 or more lines, the diff deletes 300 or more lines in total, or a whole file is deleted |
| `VERIFY-FAILED` | high | A supplied Verify report's verdict is not a pass |
| `CONFIG` | medium | A config-shaped path changed |
| `DEPENDENCY` | medium | A dependency manifest or lockfile changed |
| `SYMBOL-REMOVED` | medium | A symbol defined in deleted lines has no matching definition in the added lines of the same file |
| `BINARY` | medium | A changed file is binary; its contents cannot be reviewed from the diff |
| `NO-TEST-IN-DIFF` | info | Code files changed and no test file appears in the diff. An observation, not a failure |

## Reports

- `REVIEW.md`: Verdict, What changed (per file, plain words),
  Symbols touched, Dependents affected, Risks, Verify and Scope
  (what was supplied and what each said, or plainly that neither
  was), Honest limits.
- `review.json`: the same facts machine-readable, plus per-flag
  rule names and per-file symbol methods, for CI and GhostBench.
  A review is a pure function of its inputs, except for the
  generated-at timestamp.

Dependents come from a deliberately simple one-hop import scan:
project files that import a changed file and are not themselves
in the diff. That is not GhostScope's call graph and not a
transitive blast radius, and the report says exactly that.

Optional inputs are cited, never faked: if no Verify report is
supplied, the review says "No GhostVerify report was provided"
and claims no check ran. A supplied but unreadable report is
named as unreadable, never silently dropped.

A supplied Scope pack is cited in full, not just for its risk
reasons: the review also reports the pack's recorded reading
order, per-file changed symbols, covering tests and direct
caller counts, and its recorded pack size, all copied from
scope.json. It also reconciles the pack's changed-file list
against the diff being reviewed, naming any files listed only
in the pack or only in the diff. That comparison is a cited
fact about the two inputs (a pack may have been built for a
different range): it is never a risk flag and never changes
the verdict. If the pack records no changed-file list, the
review says no comparison was made rather than inventing one.

## Limits, stated plainly

- **Static evidence only.** "No risks flagged by these rules"
  is not a guarantee a change is safe.
- **Symbol detection is uneven by language.** Python is exact
  (stdlib `ast`); other languages are definition-line patterns,
  labelled parser-lite per file. A change inside a long
  non-Python function may be attributed to no symbol.
- **The import scan is one hop and import-shaped only.**
  Dynamic, runtime, and string-based references are missed by
  design. GhostScope's pack is the tool for blast radius.
- **No causes, intent, or quality judgements.** The review
  states what changed and what the rules flagged, nothing more.

## Troubleshooting

- **`could-not-review` (exit 2).** The diff was empty or could not
  be parsed into file changes. Check that the diff file exists and
  really is a unified diff, or, for a working-tree review, that
  there are tracked changes against `HEAD`. This verdict is never
  a clean pass.
- **"could not run git diff" / "git diff failed".** The default and
  `--staged` sources need `git` on PATH and `<project>` inside a
  git repository. Outside a repository, save a diff and pass it
  with `--diff <file>` instead.
- **"could not read diff file" (exit 2).** The `--diff` path could
  not be read. Check the path; `-` alone means stdin.
- **A supplied report is named as unreadable.** A `--verify-report`
  or `--scope-pack` that cannot be read is named in the review's
  notes, never silently dropped. Fix the path (a Scope pack may be
  the pack directory or its `scope.json`) and re-run.
- **No dependents listed, but you expected one.** The scan is one
  hop and import-shaped only: dynamic, runtime, and string-based
  references are missed by design. Use a GhostScope pack for blast
  radius.

## Out of scope (v0.1)

Building a review pack (GhostScope), running Verify checks or
tests (GhostVerify), calling a model API, approving or
requesting changes, merging, committing, posting comments,
any hosting API, cross-repo diffs, cloud/accounts/telemetry,
and any paid layer.

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

The suite is black-box: CLI tests drive `ghostreview review`
and the MCP handshake as a subprocess and skip cleanly if no
`ghostreview` CLI is discoverable. The fixture tests always run
and pin the planted cases: a clean small change, a test-only
edit, a secrets-path edit, a secret-shaped line in a normal
file, a 120-line deletion, a deleted test, a config/dependency
change, a removed symbol, a binary change, a new file, a
rename, a mixed diff carrying all three headline flag classes,
an empty diff, and a malformed non-diff, plus Verify and Scope
report fixtures in their real formats.

Fixtures live in `tests/fixtures/` (diffs, reports, and a sample
project where `app.py` imports the changed `pricing.py`, which
pins the dependents test).

## Layout

```
PLAN.md            the v0.1 plan this build implements
README.md          this file
src/ghostreview/   the implementation (core build)
tests/             black-box CLI tests + fixture-validity tests
examples/          sample project, diffs, sample reports, walkthrough
```

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
