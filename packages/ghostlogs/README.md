# GhostLogs
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostlogs/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostlogs/actions/workflows/ci.yml/actions)

A log slicer for GhostSlice. GhostSlice governs what an agent reads
from a codebase; GhostLogs governs what an agent reads from a log
file. It turns one large local log into a small incident pack: the
error windows, the repeated lines shown once with exact counts, and a
written record of everything that was left out and why.

The pack is evidence, not a diagnosis. GhostLogs shows what matched,
how often, and in what order. It never claims why the failure
happened.

## Install

Requires Python 3.10 or newer. Pure Python standard library, zero
runtime dependencies.

```
pip install .
```

That puts a `ghostlogs` command on your PATH. For development, use
`pip install -e .` instead. With no install at all, run the module
from the repo root:

```
PYTHONPATH=src python3 -m ghostlogs pack app.log -o incident-pack
```

Check the install at any time with `ghostlogs doctor` (see below).

## What it does

Given one log file and a token budget, GhostLogs writes a pack folder
with two files:

- `INCIDENT.md`, the readable pack: timeline anchors (the first and
  last lines and timestamps), an evidence overview (exact matched
  line counts by severity and by pattern, and per-hour buckets of
  line and matched-line counts), error windows with their
  surrounding context and stack traces, duplicate exemplars with
  exact occurrence counts, and a plain statement of what was not
  shown.
- `manifest.json`, the same facts in machine form: source path, size
  and sha256, the token budget and the pack estimate, and line counts
  that must reconcile exactly: total lines in = kept + collapsed +
  dropped, with dropped split by reason.

The evidence overview is counted in the same single pass, once per
line, before any window or duplicate decision: each matched line
counts once at its highest matched severity and once per pattern
it matches, and each timestamped line counts toward its hour
bucket (the timestamp exactly as written, no timezone conversion;
syslog timestamps carry no year in the source and their buckets
say so). Matched lines without a recognised timestamp are counted
separately and fall in no bucket. The overview carries counts
only, never line text, so it adds no redaction surface. At the
anchors budget tier the pack face compacts it to the counts alone
and points at the manifest for the buckets and tallies, so the
summary never crowds out the mandatory anchors.

Three things happen on the way in:

- Error windows. Lines matching the built-in patterns (FATAL,
  CRITICAL, ERROR, panic markers, traceback starts, exception names)
  open a window of context lines. Overlapping windows merge, and
  stack traces are absorbed into their window.
- Duplicate collapse. Repeated lines collapse to one exemplar with an
  exact count and first and last line numbers. Near duplicates are
  grouped after masking timestamps, numbers, hex ids, UUIDs, IPs, and
  quoted strings; each exemplar also reports how many of its copies
  were byte-identical, so over-grouping is visible rather than
  hidden.
- Redaction, on by default. Secret-shaped literals in emitted
  excerpts are replaced with a typed placeholder such as
  `[REDACTED:aws-access-key]`. The value is never printed in the
  pack, the manifest, or the terminal output. Counts per shape are
  recorded in the manifest. Covered shapes include bearer and
  Basic authorization header tokens (full base64 charset, padding
  included) and GitHub tokens in both the classic `ghp_` style and
  the fine-grained `github_pat_` style. `--no-redact` exists for local debugging
  and is recorded in the manifest when used.

## Quick start

```
ghostlogs doctor
ghostlogs pack app.log -o incident-pack --budget 4000
```

`doctor` reports the version, the token estimator in use, and the
pattern set loaded. Run it first if you are not sure the install is
healthy, or to validate a custom pattern or config file before a
pack run (see "Custom patterns" and "Config file" below).

`pack` prints a short summary like this one (from the example log in
`examples/`, packed with `--budget 2000`; the estimator name, which
depends on whether GhostSlice is reachable, is abbreviated here):

```
Packed examples/billing-api.log -> incident-pack
  lines 33 = kept 15 + collapsed 18 + dropped 0 (reconciles: True)
  windows: 1 emitted of 1 matched; duplicate groups: 2 emitted of 2
  pack estimate 708 tokens against budget 2000 (estimator: ...)
  budget tier: full - Every selected window and duplicate exemplar is shown in full.
  redactions: 1 {'aws-access-key': 1}
```

The summary states the reconciled line counts, how many windows and
duplicate groups were emitted, the pack estimate against the budget,
which budget tier shipped, and the redaction counts. If the
mandatory content alone exceeds the budget, the pack is still
written, marked over budget in the manifest and in a Pack status
section in `INCIDENT.md` itself, and the command exits nonzero (exit
1, see "Exit codes"). It never pretends a pack fit when it did not.

A worked example with a synthetic log and its checked-in pack lives
in `examples/`; see `examples/README.md`.

## Options at a glance

`ghostlogs pack` takes one positional argument and these options:

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `logfile` | yes | none | Path to the local log file. Read only; never modified. |
| `-o`, `--output` | yes | none | Pack output directory. Created if missing. |
| `--budget` | no | 8000 | Token budget for the pack. Must be positive. |
| `--window-before` | no | 3 | Context lines kept before a match. Zero or more. |
| `--window-after` | no | 5 | Context lines kept after a match. Zero or more. |
| `--patterns` | no | none | File of extra patterns, one per line (see below). |
| `--pattern` | no | none | One extra regex. Repeat the flag for more. |
| `--config` | no | none | JSON config file (see below). |
| `--no-redact` | no | off | Disable secret-shape redaction. Recorded in the manifest. |

`ghostlogs doctor` takes no positional argument. It accepts
`--patterns`, `--pattern`, and `--config` so the same extra patterns
or config a pack run would use can be loaded and validated first; a
bad regex or a bad config file fails loudly there instead of mid-run.

`ghostlogs --help`, `ghostlogs pack --help`, and
`ghostlogs doctor --help` print the same reference from the command
line, with examples. `ghostlogs --version` prints the version.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Pack written within budget, or `doctor` ran clean. |
| 1 | Pack written but over budget: even the mandatory anchors did not fit. The pack and the manifest both say so. |
| 2 | Could not run: missing input file, bad pattern file, bad config, or an invalid setting (for example a non-positive budget). No pack is written on a 2. |

## Custom patterns

The built-in pattern set is deliberately plain, and every pattern has
an id. Add your own in either of two ways; custom patterns are
severity 2, kind `custom`, and run on every line:

- On the command line: `--pattern 'connection refused'` (repeatable;
  ids are assigned as `cli-1`, `cli-2`, and so on).
- In a pattern file passed with `--patterns FILE`: one pattern per
  line, either `id = regex` or a bare regex (id auto-assigned as
  `custom-1`, `custom-2`, and so on). Blank lines and lines starting
  with `#` are ignored.

Example pattern file:

```
# my-patterns.txt
deploy-marker = DEPLOY \d+ (started|finished)
connection refused
```

```
ghostlogs pack app.log -o incident-pack --patterns my-patterns.txt
ghostlogs doctor --patterns my-patterns.txt
```

A bad regex in either route is an error (exit 2) naming the file and
line, or the offending `--pattern` value. Nothing is silently
skipped.

## Config file

`--config FILE` reads defaults from a JSON object. Allowed keys are
exactly `budget`, `window_before`, `window_after`, `patterns_file`,
and `no_redact`; an unknown key is an error (exit 2), not a warning.

```json
{
  "budget": 4000,
  "window_before": 3,
  "window_after": 5,
  "no_redact": false
}
```

```
ghostlogs pack app.log -o incident-pack --config ghostlogs.json
```

Precedence is: a value given on the command line wins, then the
config file, then the built-in default. That includes the pattern
file: `--patterns` wins over the config's `patterns_file` when both
are given. `--pattern` entries are always added on top of whichever
pattern file was selected.

## How the budget works

Emission priority is: timeline anchors first (always kept), then
error windows (highest severity, then file order), then duplicate
exemplars (highest count first). Anything that does not fit is
counted as dropped with its reason in the manifest. Windows are never
truncated in the middle.

Fit is decided by a tier ladder. The builder renders each tier,
measures the real pack, and ships the first tier that fits:

- `full`: every selected window and exemplar shown in full.
- `trimmed`: windows shown with plain context lines trimmed away;
  matched lines, trace lines, and repeat representatives kept.
- `exemplars`: error windows omitted; anchors and duplicate
  exemplars shown.
- `anchors`: only the mandatory timeline anchors shown.

The shipped tier is recorded in the manifest as `budget_tier`, with
a plain-words `budget_tier_meaning` beside it, and stated on the
face of `INCIDENT.md` whenever the tier is below `full`. The
over-budget path (pack written, marked, nonzero exit) is reached
only when even the anchors tier cannot fit. Token figures are
estimates from the GhostSlice calibrated estimator when GhostSlice
is reachable, or a documented fallback when it is not; the manifest
stamps which method was used. Estimates are not a vendor tokenizer
count.

One quirk worth knowing: the pack header names the source by the
path it was given on the command line, and the estimate counts the
pack exactly as written, so the same log invoked through a longer
path string estimates slightly higher. Measured
on the example log: a source path 62 characters longer added 28
estimated tokens. The manifest's sha256 is the pack's identity
either way; the path is provenance, not identity.

## Reading the pack

Start with `INCIDENT.md`. In order, it contains:

1. A header: source path, size, short sha256, line count, token
   budget, estimator, and the reconciled counts line.
2. Timeline anchors: first and last lines, first and last recognised
   timestamps (or a plain note that none were recognised).
3. Error windows: each headed by its line range, matched pattern id,
   and severity, with the window lines in a code block. A note under
   the heading says if consecutive repeats were collapsed in place
   or context lines were trimmed to fit.
4. Repeated lines: one line per emitted duplicate group, in the form
   `x<count> (byte-identical x<count>), lines <first>-<last>: <line>`,
   plus a separate list for repeats that occurred inside error
   windows.
5. What was not shown: the dropped counts by reason, and whether
   redaction was on or off for the run.

`manifest.json` carries the same facts for tools. The fields a
reader most often wants are `counts` (with `counts.reconciles`),
`budget_tier` and `budget_tier_meaning`, `over_budget`,
`pack_estimated_tokens` against `budget_tokens`, `windows` and
`duplicates` (including `duplicates.window_list` for repeats inside
windows), `redaction` (enabled flag plus counts by shape), and
`limits`, the honest-limits list stated in writing. The manifest
also lists every pattern that was loaded, so a pack can be checked
against the pattern set that produced it.

## Troubleshooting

- "No lines matched the pattern set" in the pack: the run worked;
  no line matched any loaded pattern. That is a statement about the
  patterns, not proof that nothing went wrong. Widen the search with
  `--pattern` or a `--patterns` file, and confirm with `doctor` that
  the extra patterns loaded.
- Exit 1 (over budget): the pack was still written and is still
  reconciled; it holds only the mandatory anchors. Raise `--budget`,
  or accept the anchors-only pack knowingly. The Pack status section
  in `INCIDENT.md` states the outcome on the face of the pack.
- Exit 2: read the message on stderr. It names the missing file, the
  bad regex (with file and line for a pattern file), the unknown
  config key, or the invalid setting. Fix that input and rerun; no
  pack was written.
- The pack estimate differs between two runs of the same log: check
  the source path in the header first. The estimate counts the pack
  exactly as written, header path included, so a longer path
  estimates slightly higher (see the quirk note above). Compare the
  manifest sha256 values to confirm the source bytes are identical.
- An empty log still produces a pack: the anchors section says the
  source file is empty, and the counts reconcile at zero.

## Safety and scope

- The source log is never modified, moved, or copied wholesale. Only
  selected, redacted excerpts are emitted. The tests hash the source
  before and after a run to hold this.
- Local files only. No network, no upload, no log server, no account.
- One file per pack. No live tailing or daemon mode in v0.1.
- Pure Python standard library, zero dependencies.

## Honest limits

- Pattern-based finding only sees what the patterns name. A failure
  written in words no pattern matches produces a pack with no error
  windows, and the pack says exactly that: no lines matched the
  pattern set. It never says nothing went wrong.
- Near-duplicate masking can over-collapse: two genuinely different
  errors that differ only in a masked part (a number, an id) share
  one exemplar. The exemplar is the first occurrence verbatim and the
  byte-identical count is shown beside the total, but the grouping
  can still hide a distinction that mattered.
- Repeated lines inside an error window are counted separately from
  the routine duplicate groups: the manifest carries them as window
  duplicate groups with exact occurrence counts, and the pack lists
  them under "Repeated lines inside error windows". Inside the
  window itself, consecutive repeats collapse in place under a note,
  so the window shows one copy while the exact total is stated in
  the counts.
- Stack trace absorption covers Python tracebacks, Java-style frames
  and Caused by chains, and generic indented continuations. Exotic
  formats may split a trace across windows.
- Secret-shape matching is exact about lengths, by design. The AWS
  access key shape is `AKIA` or `ASIA` plus exactly 16 characters
  (20 in total, the same shape GhostSlice's guard uses), so a
  longer or shorter look-alike is not that shape and is not
  redacted under that name. The other provider shapes (GitHub,
  `sk-`, Slack, JWT, bearer) are minimum-length. A generic
  assignment (`password=...` and kin) is redacted only when the
  name looks sensitive and the value is at least 8 characters with
  at least 4 distinct characters, and is not an obvious placeholder.
  Redaction lowers risk; it is not a guarantee that every credential
  form is caught.
- The log is read in a single streaming pass, so very large files are
  fine, but the duplicate signature table grows with the number of
  distinct normalised lines.

## Layout

- `src/ghostlogs/`: the core (patterns, analysis, redaction, pack
  writer, CLI).
- `tests/`: black-box tests against the CLI, including planted-repeat
  and planted-secret fixtures with exact ground truth.
- `examples/`: a synthetic noisy log and the incident pack built
  from it.

MIT licensed, same as the rest of the GhostSlice family.

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
