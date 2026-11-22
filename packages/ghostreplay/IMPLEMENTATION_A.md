# GhostReplay v0.1 - Implementation Notes (Agent A, core)

Built Oct 14, 2026 per ~/workspace/ghostreplay/PLAN.md.
Ownership honoured: only src/**, pyproject.toml, and this file were
written by Agent A. tests/**, README.md, examples/** are Agent B's
and were not edited. No network, no push, no publish, no spend.

## Naming caution (from PLAN.md, not renamed)
The product name used throughout is GhostReplay, per the parent
brief. PLAN.md records that GhostGuard already has a "replay"
add-on (policy backtest) and that GhostTrace is the reserve
alternative. The collision is flagged in src/ghostreplay/__init__.py
docstring for Ryan's rename decision; nothing was renamed here.

## Layout
- pyproject.toml: name ghostreplay 0.1.0, stdlib only (dependencies
  = []), console script ghostreplay = ghostreplay.cli:main,
  Python >= 3.10.
- src/ghostreplay/tokens.py: GhostSlice estimator method v2
  reimplemented (BPE-like split + per-family calibration factors
  copied from GhostSlice tokens.py), so numbers are comparable
  without importing GhostSlice. Estimates always labelled.
- src/ghostreplay/secrets.py: secret-shaped patterns (private key,
  AKIA/ASIA, gh*_ tokens, sk- keys, slack, generic assignments,
  URL passwords, bearer). Findings are {source, line, type} only.
  sanitize() strips secret-shaped spans from any emitted string;
  reports never quote transcript text.
- src/ghostreplay/transcript.py: ingest for the ONE documented
  v0.1 format (below), normalising to canonical ghostreplay-session/1.
- src/ghostreplay/bundle.py: GhostSlice manifest join + path matching
  (exact relative, project-relative, unique suffix; ambiguous = None).
- src/ghostreplay/analysis.py: sent-vs-referenced, re-reads, mode
  friction (file + symbol), rule repetition (3-line shingles,
  Jaccard >= 0.85, substantive blocks only: >= 3 lines or >= 160
  chars, so one-line prompts are not padded into "rules").
- src/ghostreplay/report.py: REPLAY.md + replay-report.json writers
  (deterministic, see reproducibility below).
- src/ghostreplay/propose.py: proposal aggregation + writers
  (ghostreplay-proposal.json + PROPOSAL.md).
- src/ghostreplay/profile.py: replay-section config (unknown keys
  fail loudly), change validation, GhostSlice-loader validation of
  the resulting profile when importable (installed or sibling
  checkout, with rollback on rejection), backup/restore.
- src/ghostreplay/ledger.py: .ghostreplay-history.jsonl append +
  trend summary (latest record per session for the trend rows).
- src/ghostreplay/cli.py: ingest / analyse (alias analyze) /
  propose / apply / restore / trend. Exit codes: 0 ok, 1 apply
  could not get input, 2 user error.

## The one documented transcript format
Claude Code session transcripts as saved locally. Form A: JSONL,
one object per line, entries with type/sessionId/cwd/timestamp and
message {role, content as string or block list (text / tool_use
with file_path-style inputs / tool_result), optional usage, model}.
Form B: a single JSON document, a list of those entries or
{"messages": [...]}. Anything else fails loudly at ingest (exit 2,
naming the line/problem) rather than being analysed badly. A turn =
one user entry plus following assistant entries. Canonical sessions
are stored sanitized (secret-shaped spans redacted at ingest) with
a transcript sha256; provider-reported usage is carried under
reported_* keys and never blended with estimates.

## Analysis semantics (with the mandatory qualifier)
- "Not referenced in transcript" is the only label used, never
  "not needed", with the transcript-incompleteness qualifier on
  every surface (report dict, REPLAY.md, proposal evidence). The
  report also carries the alias key "not_referenced" for machine
  consumers; the qualified key "not_referenced_in_transcript" is
  canonical.
- Re-read = file referenced in >= 2 distinct turns; cost =
  extra turns x bundle sliced_tokens (estimate). Qualifier in the
  report notes waste % can exceed 100% of the bundle because each
  re-read spends tokens again.
- Mode friction = bundle file sent non-full that the session later
  direct-Reads (Read tool_use), per file; per symbol when the
  symbol (manifest symbols_included or file outline) is mentioned
  in a direct-read turn's text.

## Propose / apply (propose-only, enforced)
- propose aggregates >= min_sessions (default 3, from the
  profile's "replay" section; unknown replay keys are a loud
  error). Below the minimum it writes status
  "insufficient-sessions", zero applicable changes (diagnostics
  kept in a separate field), and apply refuses it (exit 2).
- Changes: mode -> exclude (present in >= min_unreferenced_sessions
  bundles, referenced in 0 of those, evidence cites counts and
  average estimated sliced tokens); mode -> full (friction turns
  >= threshold); entry_point -> pin (referenced in every session,
  >= 2 turns in one). Rule-repetition clusters across >= 2
  sessions are recall_candidates, never profile changes.
- apply has NO --yes flag by design: it prints the diff and reads
  an explicit "yes"/"y" from the terminal. Backup is
  .ghostslice.json.bak when a profile existed, else a
  .ghostslice.json.ghostreplay-created marker; restore reverses
  both. A resulting profile that GhostSlice's own loader rejects
  is rolled back automatically.

## Smoke test (run Oct 14, 2026, fixture in /tmp/ghostreplay-smoke)
Synthetic project (src/hot.py signatures, src/cold.py, src/main.py,
docs/legacy/old.md) + GhostSlice-shaped manifest + 3 Claude Code
JSONL sessions where hot.py is Read in 5 distinct turns per session
and cold/old are never referenced; session 1 carries a planted
sk-ant- shaped secret; a substantive 4-line rule block repeats in
all 3 sessions.
- ingest: 11 entries / 6 turns, secret finding recorded as
  source+line+type only. Form B {"messages":[...]} ingest also OK.
- analyse: sent 475 est.; not-referenced 338 est.; re-read waste
  480 est. (4 extra x 120); friction files 1 (src/hot.py). PASS.
- Privacy: grep for the planted secret across all outputs
  (.ghostreplay/, REPLAY.md, replay-report.json, proposal, ledger)
  = zero hits. PASS.
- Reproducibility: two analyse runs to different out dirs produce
  byte-identical replay-report.json and REPLAY.md (diff clean).
  PASS (report artifacts carry no wall-clock timestamps; the
  ledger, a history, is stamped and excluded from this claim).
- Unrecognised transcript ("hello not json"): exit 2, loud error
  naming the shape. PASS.
- propose (3 sessions): status ready, 3 changes (exclude cold,
  exclude old, hot signatures->full), exactly 1 recall candidate
  (the rule block) after the substantive-block filter. PASS.
- propose (1 session): status insufficient-sessions, 0 applicable
  changes; apply of it refused with exit 2. PASS.
- apply: "no" writes nothing; piped "yes" applies 3 changes; the
  resulting .ghostslice.json validates under GhostSlice's own
  load_profile_file (sibling checkout). PASS.
- restore: with no prior profile, removes the created profile;
  with a pre-existing profile, restores its exact bytes from .bak.
  PASS.
- Entry-point pin: clean fixture with a.py referenced in 2 turns
  x 3 sessions -> 1 change (entry_point a.py pin). PASS.
- Zero-waste fixture (all files referenced exactly once, 3
  sessions): proposal changes = [] and recall candidates = [].
  PASS.
- trend: prints per-session rows + mean waste from the ledger.
  PASS.
- Install: fresh venv `pip install .` -> `ghostreplay --version`
  = 0.1.0, installed CLI trend works. PASS.

## Agent B contract suite
After Agent B's tests landed, the core was run against them
unmodified except for one alignment fix in Agent A's own file
(added the "not_referenced" alias key above):
PYTHONPATH=src python3 -m pytest tests -q -> 21 passed.
