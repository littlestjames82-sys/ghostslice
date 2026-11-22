# GhostLogs v0.1 - Agent A implementation record

Core owner deliverables: PLAN.md, pyproject.toml, src/ghostlogs/**
(tokens, redact, patterns, analyze, pack, cli). tests/**, README.md,
and examples/** are Agent B's and were not touched.

## What was built

- `ghostlogs pack <logfile> -o <dir> --budget N` writes an incident
  pack: INCIDENT.md (human pack) + manifest.json (machine record).
- `ghostlogs doctor` reports version, estimator in use, and the
  loaded pattern set; bad pattern/config input fails loudly (exit 2).
- Exit codes: 0 pack within budget, 1 pack written but over budget,
  2 could not run (missing input, bad pattern file, bad config).

Design, per PLAN.md:
- Single streaming pass over the source in binary mode, one line at
  a time. The whole file is never loaded. Retained state: capped
  window lines (100,000 stored across all windows), the duplicate
  signature table, a before-context pending buffer, counters.
- Windows: a pattern match opens a window (configurable
  before/after context, overlapping bursts merge naturally because
  each new match extends the open window). Stack traces absorb:
  indented lines, Python/Java frame lines, Caused by chains, and
  JVM elision lines extend the window past its after-context, up to
  200 absorbed lines per window.
- Duplicate collapse with the precedence rule stated in PLAN.md:
  the first burst of an error is windowed in full; consecutive
  repeats inside a window collapse in place (counted, with line
  ranges kept for exact accounting); later bursts of an
  already-windowed error are suppressed as matches
  (suppressed_repeat_matches in the manifest) and collapse into
  duplicate exemplars. Near-duplicate signatures mask timestamps,
  UUIDs, IPs, quoted strings, hex ids, and numbers; each exemplar
  records occurrences plus byte-identical copies.
- Redaction by default: shape names follow GhostSlice's secret
  guard (aws-access-key, github-token, openai-or-anthropic-key,
  slack-token, private-key, jwt, bearer-token, url-password,
  generic-assignment). Values are replaced with [REDACTED:shape]
  and never written anywhere. --no-redact is recorded in the
  manifest when used.
- Tokens: GhostSlice's calibrated estimator (method v2) when a
  GhostSlice install or sibling checkout is reachable, else a
  documented raw-split fallback; the manifest stamps method and
  source either way.
- Counts reconcile by construction and are re-checked at pack
  time: total = kept + collapsed + dropped, dropped split into
  routine / duplicate_not_emitted / window_not_fitted /
  window_store_cap, and the manifest carries "reconciles": true
  only when both equations hold.
- Performance: per-line token estimates and signatures are memoised
  on exact line text (identical lines, identical results), and the
  builtin patterns sit behind a needle prefilter (one combined
  substring regex; custom patterns always run in full). Both are
  pure speed: outputs were byte-identical before and after on every
  fixture below.

## Smoke results (all run against this core, Oct 14, 2026)

Fixture app.log (182 lines: heartbeat repeats, a 120-line repeated
ERROR burst, a traceback, a planted AKIA-shaped key and a planted
password= assignment inside the window's reach):
- budget 4000: 182 = 16 kept + 166 collapsed + 0 dropped,
  reconciles true. Window stored 13 lines with 123 in-window
  repeats collapsed. Pack 755 estimated tokens (was 3,885 before
  in-window collapse existed). Both planted values appear 0 times
  in INCIDENT.md and manifest.json; manifest redaction counts:
  aws-access-key 1, generic-assignment 1. Source sha256 identical
  before and after.
- budget 300: window does not fit; 182 = 3 + 43 + 136 dropped
  (all 136 window_not_fitted), exit 1, over_budget true.
- budget 60: anchors only; 182 = 2 + 0 + 180, exit 1.

Fixture bursts.log (62 lines, three separated bursts of the same
ERROR with routine lines between): 1 window (first burst),
suppressed_repeat_matches 16, the later bursts form a duplicate
group x16; 62 = 6 + 56 + 0, reconciles true.

Fixture anchorbug.log (6 lines, last line repeats line 1): exposed
a real off-by-one during verification (an anchor line that is a
non-exemplar member of an emitted group was counted as both kept
and collapsed; at 350 MB scale this showed as dropped = -1). Fixed
by tracking the first/last lines' duplicate-group signatures in
the analyser and adjusting in pack.py; the fixture now reconciles
(6 = 4 + 2 + 0) and no other fixture's numbers changed.

Clean log (3 INFO lines): pack written, "no lines matched the
pattern set" wording, exit 0. Empty log: pack written, exit 0.
Missing file: exit 2. Bad pattern file (unclosed regex) and bad
config (unknown key): exit 2 with the file, line, and key named.
Custom pattern file + JSON config: applied (config budget 1500
honoured). --no-redact: manifest redaction.enabled false, and the
planted example key then appears in the pack, which is exactly why
the flag is recorded.

Fresh-venv `pip install .`: installed CLI reports 0.1.0 and
reproduces the bursts pack counts.

Large log: 349,558,528 bytes / 4,400,004 lines (synthetic service
log, doubled copy), budget 8000. Final run after the anchor fix:
4,400,004 = 104 kept + 4,399,900 collapsed + 0 dropped,
reconciles true, pack 5,345 estimated tokens, exit 0, peak RSS
47 MB (the 350 MB source is never resident). Wall time 338s on
the final run and 93.8s on an earlier identical run; the spread
is parallel-build contention on this box (~40 agents), not input
variance.

## Known limits (honest)

- Throughput is regex-bound: on this machine, under contention
  from ~40 parallel builders, the 350 MB run took minutes, not
  seconds. The 200k-line profile slice takes ~3.6s unloaded. The
  memoisation helps repetitive logs most; an all-unique-lines log
  runs at raw regex speed.
- Minimum pack size: INCIDENT.md scaffolding (headers, anchors
  section, counts, limits) is itself ~370-470 estimated tokens, so
  budgets below roughly 500 always report over_budget even with
  everything optional dropped. The exit code and flag say so; the
  budget is not silently reinterpreted.
- The duplicate signature table grows with distinct normalised
  lines; counts stay exact, but a pathological all-unique log
  makes the table the memory ceiling (49 MB peak on the synthetic
  above, which is highly repetitive).
- In-window collapse is consecutive-only: identical lines inside a
  window separated by other lines are stored individually (context
  integrity), though they still count toward their duplicate group
  only if they reach duplicate accounting, which window lines do
  not. Stated in the manifest limits.
- Traceback absorption covers Python tracebacks, Java frame and
  Caused by lines, and generic indented continuations. Exotic
  formats may split across windows.
- Redaction shapes are conservative and log-oriented; a secret in
  a shape not listed (for example a bare 40-char AWS secret with
  no AWS context words) is not caught. Dropped lines are never
  emitted, so only kept/collapsed content is redacted because only
  it is shown.
- Timestamps: ISO 8601, syslog, and one bracketed form. First/last
  timestamp anchors are the first/last recognised in file order;
  no timezone conversion is attempted.
- One file per pack; binary input is decoded as UTF-8 with
  replacement characters and processed line-wise regardless.

## Addendum: Agent B suite against the final core

Agent B's suite (tests/, 26 tests) run by Agent A against the
final core: **26 passed, 0 failed.** Two of B's findings were
fixed core-side during the run (B's REPORT_B.md has the finding
records; no test was edited by Agent A):

- D2/D3 class, budget honesty: B caught packs whose finished
  estimate landed over a budget that selection believed it had
  met. Root cause was the same family as the anchor bug plus an
  under-measured selection reserve: the INCIDENT.md scaffolding
  really costs ~330-370 estimated tokens, but the reserve was
  150. The reserve is now 340 and the not-shown prose was
  tightened; test_budget_600_lands_at_or_under_budget passes
  outright, and the honest over-budget path at budget 150 still
  exits 1 with over_budget true.
- D1, true count of a repeated error: B pinned this as a strict
  xfail against the first-landed core. The in-window collapse
  note, exemplar counts, and manifest repeat counts now state the
  true count; the test passes outright (its xfail marker was
  removed on the fix landing, per the comment in the test file).

## Gates held

Stdlib only (zero dependencies in pyproject), local only, no
network code anywhere under src/, no GitHub push, no PyPI/publish,
no announcements, no spend. Source logs are opened read-only and
never modified (sha256 verified in smoke).
