# GhostReplay
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostreplay/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostreplay/actions/workflows/ci.yml/actions)

**See what your agent actually used, not what you sent it.**

GhostSlice builds an agent context bundle from static analysis. But real
sessions disagree with static guesses: files ride along in every bundle
and are never touched, the same file is re-read turn after turn, and a
symbol served as signatures gets expanded to full again and again.
GhostReplay replays recorded agent sessions against the GhostSlice
bundle that produced them and turns the waste into evidence: a per-session
report, and a proposed `.ghostslice.json` profile diff where every change
cites its session counts.

By Ghost Developer Studio. MIT licensed. **Zero dependencies** (Python
standard library only), **local-first**: no network calls, no telemetry,
your transcripts never leave the machine.

Position in the Ghost stack: GhostSlice governs what an agent *reads*,
GhostVerify checks a slice was *enough*, GhostBench measures *controlled*
comparisons, GhostReplay learns from *actual runs* in the field.
Agent Seatbelt governs what an agent *does*.

> Naming note: "GhostReplay" is a working name. A GhostGuard add-on also
> uses the word "replay" (policy backtest, a different job); the reserve
> name is GhostTrace. The final call is a deliberate gate, recorded in
> PLAN.md.

Contents: [Install](#install) ·
[Try the bundled demo](#try-the-bundled-demo-2-minutes) ·
[Quickstart](#quickstart-your-own-project) ·
[Commands at a glance](#commands-at-a-glance) ·
[Transcript format](#the-transcript-format-v01-one-shape-documented-exactly) ·
[What a report shows](#what-a-report-shows) ·
[Propose-only](#propose-only-always) ·
[Configuration](#configuration-optional) ·
[Privacy](#privacy-rules-plain-words) ·
[Honest limits](#honest-limits) ·
[Troubleshooting](#troubleshooting) ·
[Tests](#tests) · [Layout](#layout)

## Install

Requires Python 3.10 or newer. No install needed to try it from a
checkout:

```bash
cd ghostreplay
PYTHONPATH=src python3 -m ghostreplay --help
```

Or install it (still zero dependencies):

```bash
pip install .
ghostreplay --help
```

Every command also has its own help, with defaults and an example:

```bash
ghostreplay analyse --help
ghostreplay propose --help
```

## Try the bundled demo (2 minutes)

The fastest way to see what GhostReplay does, with no project of your
own:

```bash
# From the repo root, no install needed:
sh examples/run_demo.sh

# Or the same thing by hand:
PYTHONPATH=src python3 -m ghostreplay analyse \
    examples/sample_project examples/transcripts/planted_waste_1.jsonl \
    --bundle examples/sample_bundle --out /tmp/replay-demo
# Then read /tmp/replay-demo/REPLAY.md
```

The demo transcript has planted waste, so a correct report finds
exactly two things (full expectations in
[`examples/EXPECTED_OUTPUT.md`](examples/EXPECTED_OUTPUT.md)):

- `src/hot.py` re-read in 5 distinct turns: 268 estimated re-read
  tokens wasted.
- `src/legacy.py` not referenced in the transcript: 86 estimated
  tokens sent for nothing the transcript can show.

## Quickstart (your own project)

You need three things: a project directory, at least one recorded
transcript on disk (see [the format](#the-transcript-format-v01-one-shape-documented-exactly)),
and, for the bundle comparisons, the GhostSlice bundle that produced
the session. Without a bundle, `analyse` still runs, but the
sent-vs-referenced, re-read cost, and friction sections are reported
as unavailable rather than guessed.

```bash
# 1. (Optional) Register a transcript as a canonical session.
#    analyse/propose also accept a raw transcript directly, so you
#    can skip this step; ingest is useful when you want a stable
#    session file to reuse across runs.
ghostreplay ingest ~/my-project ~/sessions/session.jsonl
#    -> ~/my-project/.ghostreplay/<session-id>.json

# 2. Analyse one session against the bundle that produced it.
#    If --bundle is omitted, GhostReplay looks for
#    ~/my-project/.claude_context/ (the default bundle location).
ghostreplay analyse ~/my-project ~/sessions/session.jsonl \
    --bundle ~/my-project-context --out /tmp/replay-out
#    -> /tmp/replay-out/REPLAY.md and /tmp/replay-out/replay-report.json
#    Also appends one record to ~/my-project/.ghostreplay-history.jsonl

# 3. Propose profile improvements from at least 3 sessions.
#    One session can be analysed, but not proposed from (see
#    "Propose-only, always" below).
ghostreplay propose ~/my-project s1.jsonl s2.jsonl s3.jsonl \
    --bundle ~/my-project-context --out /tmp/replay-prop
#    -> /tmp/replay-prop/ghostreplay-proposal.json + PROPOSAL.md
#       (a proposal, nothing applied)

# 4. Apply only after reading the diff, with an explicit terminal yes.
#    There is deliberately no --yes flag.
ghostreplay apply ~/my-project --proposal /tmp/replay-prop/ghostreplay-proposal.json
#    -> keeps the old profile as .ghostslice.json.bak;
#       `ghostreplay restore ~/my-project` puts it back

# 5. Watch cost and waste over time (needs at least one analyse run).
ghostreplay trend ~/my-project
```

### Where files go

| File | Written by | What it is |
|---|---|---|
| `.ghostreplay/<session-id>.json` | `ingest` | Canonical session (secret-redacted) |
| `REPLAY.md`, `replay-report.json` | `analyse` | Per-session report (human + machine form) |
| `ghostreplay-proposal.json`, `PROPOSAL.md` | `propose` | Proposed profile diff with evidence |
| `.ghostreplay-history.jsonl` | `analyse` | Append-only trend ledger, in the project root |
| `.ghostslice.json.bak` | `apply` | Backup of the profile before an apply |

Defaults are shown above; every writer honours `--out` / `-o` where
the command takes one. Run `ghostreplay <command> --help` for the
exact default for that command.

## Commands at a glance

| Command | Purpose | Writes a profile? |
|---|---|---|
| `ingest <project> <transcript>` | Parse a transcript into a canonical session file | No |
| `analyse <project> <session>` (alias `analyze`) | Report on one session: re-reads, unreferenced files, friction | No |
| `propose <project> <session...>` | Draft a profile diff from 3+ sessions, with evidence | No, proposal only |
| `apply <project>` | Apply a ready proposal after a typed `yes` | Yes, with backup |
| `restore <project>` | Undo an `apply` from the backup | Restores backup |
| `trend <project>` | Cost and waste per session over time, from the ledger | No |

Exit codes: `0` ok (declining an `apply` is also `0`: a human said
no), `1` refusal with nothing applied (for example, no terminal
input at the `apply` prompt), `2` user error (bad input,
unrecognised transcript format, invalid profile or proposal).

## The transcript format (v0.1: one shape, documented exactly)

GhostReplay v0.1 reads **Claude Code session transcripts as saved locally:
JSONL, one JSON object per line**. Each line is expected to carry:

- `type`: `"user"` or `"assistant"` (other line types are ignored),
- `sessionId`: the session identifier,
- `timestamp`: ISO-8601,
- `message.role` and `message.content`.

A single JSON document is also accepted: either a list of entries in
the same shape, or an object `{"messages": [...]}`.

Minimal example (two lines of a transcript):

```jsonl
{"type": "user", "sessionId": "s1", "timestamp": "2026-10-14T12:00:00Z", "message": {"role": "user", "content": "Fix the parser"}}
{"type": "assistant", "sessionId": "s1", "timestamp": "2026-10-14T12:00:05Z", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "src/app.py"}}]}}
```

File usage is read from assistant `tool_use` content blocks: a block with
`"name": "Read"` (or `"Edit"`) and `input.file_path` set to the project
relative path counts as a reference to that file. Text content blocks are
scanned for bundle file paths as secondary references.

Any other shape fails loudly with a format error rather than being
analysed badly. Fixture transcripts in exactly this shape live in
`tests/fixtures/sessions/` and `examples/transcripts/`. The full
field-by-field spec, including the canonical session format that
`ingest` writes, is the module docstring in
`src/ghostreplay/transcript.py`.

## What a report shows

`REPLAY.md` / `replay-report.json` for one session:

- **Re-reads**: a file named as a tool input in N distinct turns,
  with its token total from the bundle manifest. A text mention is
  a reference, not a re-read, and is never charged the file's
  tokens.
- **Turn timeline**: one row per turn with its direct reads,
  edits, re-read files, and the re-read tokens spent in that turn
  (with a running cumulative total that sums to the re-read
  waste total).
- **Not referenced in transcript**: bundle files the session never
  mentioned, read, or edited, with the tokens each one cost. The label is
  always the qualified one. A transcript can miss silent or
  provider-side reads, so "not referenced" is evidence for a human, not a
  verdict that the file is "not needed".
- **Mode friction**: symbols first served as signatures that the session
  then expanded to full, counted per symbol.
- **Rule repetition**: near-duplicate instruction blocks repeated across
  sessions, flagged as candidates for GhostRecall (the project-memory
  companion).
- **Re-read hotspots** (in `propose`, not in a single-session
  report): files re-read in at least 2 analysed sessions, with
  total extra reads and estimated re-read tokens across sessions.
  Hotspots are evidence for a human, not profile changes, and
  `apply` ignores them.
- **Totals**: turns, estimated tokens in, estimated waste by category.
  Token figures come from the GhostSlice bundle manifest and the shared
  estimator, and are labelled **estimates**. Provider-reported usage
  figures, when a transcript carries them, are recorded separately as
  *reported* and never blended with estimates.

Reading a proposal (`PROPOSAL.md`): every proposed change is one line
(a mode change such as `src/legacy.py: full -> exclude`, or an
entry-point pin) followed by its evidence line, for example "present
in 3/3 bundles, referenced in 0/3 sessions, ~86 estimated sliced
tokens per session". If there is nothing worth proposing, the changes
list is empty. That is a valid, honest result, not an error.

## Propose-only, always

`propose` never touches your profile. `apply` prints the diff, asks for
an explicit `yes` in the terminal, backs the old profile up to
`.ghostslice.json.bak`, and `ghostreplay restore` undoes it. A proposal needs
at least 3 sessions by default: a single session can be analysed, but one
odd run should not rewrite a profile. There is no silent auto-tuning,
and there will not be one without a separate explicit decision.

## Configuration (optional)

Thresholds can be tuned in the `replay` section of the project's
`.ghostslice.json`. Absent section means the defaults below. Unknown
keys, wrong types, and non-positive values fail loudly rather than
being ignored.

```json
{"replay": {"min_sessions": 3, "min_unreferenced_sessions": 2, "friction_threshold": 2}}
```

| Key | Default | Meaning |
|---|---|---|
| `min_sessions` | 3 | Sessions required before a proposal is `ready` |
| `min_unreferenced_sessions` | 2 | Sessions a file must be present-but-unreferenced in before an exclude is proposed |
| `friction_threshold` | 2 | Direct-Read turns (total) before a non-full file is proposed as `full` |

A fourth key, `min_reread_turns` (default 2), is also accepted by
the config loader; re-reads themselves are always reported by
`analyse` from 2 distinct turns.

## Privacy rules (plain words)

- Transcripts are sensitive: they can hold proprietary code, personal
  prompts, and keys. GhostReplay is local-only and makes no network
  calls.
- Reports, proposals, and ledgers **never quote a secret-shaped string**.
  A secret finding is recorded as path + line + type only, matching the
  GhostSlice secrets guard.
- Reports are written where you point `--out`, and the ledger
  (`.ghostreplay-history.jsonl`) lives in the project only when a command
  writes it. Nothing is uploaded or shared, ever.

## Honest limits

- Transcript incompleteness is the central limit: see the qualified
  label above. Treat proposals as evidence, check them, then apply.
- One transcript format in v0.1. That shape will change upstream
  eventually; GhostReplay pins the shape it supports and fails loudly on
  a shape it does not recognise.
- GhostReplay measures context *use*, not answer quality. Task outcomes
  are GhostBench's job.

## Troubleshooting

- **`unrecognised transcript shape` (exit 2)**: the file is not the
  one documented format above. Check that it is Claude Code JSONL
  (or the single-JSON form), not another agent's export. GhostReplay
  will not guess at other shapes.
- **`analyse` says "no bundle manifest joined"**: no `--bundle` was
  given and there is no `.claude_context/manifest.json` in the
  project. Pass `--bundle <bundle-dir-or-manifest.json>` to get the
  sent-vs-referenced sections.
- **`propose` status is `insufficient-sessions`**: fewer than
  `min_sessions` (default 3) sessions were supplied. The proposal
  file still lists what it saw, as diagnostics only, with no
  applicable changes.
- **`trend` says there is no history yet**: run `analyse` at least
  once first; `analyse` is the command that appends to the ledger.
- **`apply` changed nothing**: either the proposal had no profile
  changes (check `PROPOSAL.md`), or the prompt was not answered with
  `yes`. Both are by design; re-run `apply` when you are ready.
- **`restore` says there is nothing to restore**: there is no
  `.ghostslice.json.bak` (and no created-profile marker) in the
  project, which means no `apply` is outstanding to undo.

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

The suite encodes the PLAN.md verification bar: a planted-waste fixture
(one file re-read exactly 5 times, one bundle file never referenced)
must produce both findings with manifest-true token figures; zero-waste
fixtures must propose an *empty* diff; a planted secret-shaped string in
a fixture transcript must appear in zero output files; identical re-runs
must produce identical report totals. Fixture-integrity tests
(`tests/test_fixtures.py`) pass without a core; the CLI contract tests
require the core and fail (not skip) when it is absent.

## Layout

```
src/ghostreplay/    the package (CLI: ingest / analyse / propose / apply / restore / trend)
tests/              contract tests + fixtures (project, bundle, sessions)
examples/           sample project, sample bundle, sample transcripts, demo script
PLAN.md             the original product plan and verification bar
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
