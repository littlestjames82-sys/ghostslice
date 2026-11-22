# GhostReplay - Agent B report (tests / README / examples)
Date: Oct 14, 2026. Scope owned: tests/**, README.md, examples/**, REPORT_B.md.
No src/** or pyproject.toml edits. No network, no push, no publish, no spend.

## Result: PASS - 21/21 tests green against Agent A's landed core

Final run (repo root, core present at src/ghostreplay with cli.py):
`PYTHONPATH=src python3 -m pytest tests -q` -> **21 passed**.

Breakdown:
- tests/test_fixtures.py - 7 passed. Pure fixture-integrity tests (pass
  with or without a core): manifest totals are internal sums, manifest
  sha256 matches bundle file bytes, all 9 fixture sessions are valid
  JSONL with session ids, planted waste reads src/hot.py exactly 5
  times, "legacy" appears nowhere in planted sessions, zero-waste
  sessions reference every bundle file exactly once, planted secret is
  present in the secret fixture INPUTS (so the privacy test is not
  vacuous) and nowhere else.
- tests/test_analyse.py - 4 passed. Planted-waste contract: REPLAY.md
  + replay-report.json written; re-read finding for src/hot.py across
  5 distinct turns; never-referenced finding for src/legacy.py carrying
  the manifest sliced_tokens (86); REPLAY.md uses the qualified label
  "not referenced in transcript".
- tests/test_propose.py - 3 passed. 3 planted sessions -> proposal
  (ghostreplay-proposal.json) citing src/legacy.py with count evidence;
  3 zero-waste sessions -> EMPTY changes list; 1 session -> no changes
  and the >=3 threshold explained in output.
- tests/test_privacy.py - 1 passed. Planted secret-shaped string
  (AKIAIOSFODNN7EXAMPLE, the AWS documentation example shape, not a
  real key) appears in ZERO files produced by analyse + propose,
  including the .ghostreplay-history.jsonl ledger in the project dir,
  and in neither stdout nor stderr.
- tests/test_reproducibility.py - 1 passed. Two independent analyse
  runs produce identical report totals.
- tests/test_cli_contract.py - 4 passed. --help lists ingest / analyse
  / propose / apply / trend; garbage transcript fails non-zero with a
  format error named; ingest exit 0; apply answered "no" leaves
  .ghostslice.json byte-identical (sha256 compared).

## Live demo verification (matches examples/EXPECTED_OUTPUT.md exactly)
Analyse of the examples pair reports: sent 344 est. tokens;
not referenced 86 (src/legacy.py); re-read waste 268 = (5 distinct
turns - 1) x 67 (src/hot.py manifest sliced_tokens); rereads entry
{path: src/hot.py, distinct_turns: 5, extra_reads: 4}.

One honest observation for the parent: on this deliberately
pathological fixture the core's estimated_waste_percent_of_sent is
102.9% (re-read waste counts re-sends beyond the single sent copy, so
waste can exceed 100% of sent on re-read-heavy sessions). Arithmetic
verified by hand: 86 + 268 = 354 waste / 344 sent. Whether the percent
should be capped or relabelled is a core (Agent A) presentation call;
Agent B only records it.

## Fixture design decisions (so the contract is unambiguous)
- Turn model: a turn starts at each user entry. The planted session
  therefore spreads its 5 hot.py Reads across 5 user turns (an early
  draft had all 5 in one turn, which the core correctly does not count
  as re-reads; fixture fixed, not the core).
- The fixture Edit of src/app.py sits in turn 1 with its reads. When it
  was in the last turn, the core counted app.py as re-referenced across
  turns (+74 tokens) and the "exactly the planted waste" expectation
  broke; fixture fixed.
- All bundle modes are "full" so manifest sha256 == file bytes and the
  integrity test can be exact. Mode friction is therefore exercised
  only as a zero-finding category in these fixtures; a signatures-mode
  friction fixture is a recommended follow-up once the parents decide
  they want one.
- Token figures in the fixture manifest are a documented chars/4
  fixture estimate; the manifest is the ground truth the core joins
  against, and tests assert manifest consistency, never estimator
  agreement with GhostSlice's calibrated estimator.
- Tests always run against a COPY of the fixture project: analyse and
  ingest write into the project dir (ledger, canonical session), and
  the shared fixture must stay pristine. Verified clean after runs.

## Assumptions: made, then resolved against the landed core
Agent A's core landed DURING this build, so initial assumptions in
conftest.py were checked against the real CLI and corrected in the
tests/README (proposal file is ghostreplay-proposal.json + PROPOSAL.md,
not profile-diff.json; restore is its own command, not apply
--restore; change records are kind/target/current/proposed/evidence).
No open assumptions remain except: the README Layout section and the
pyproject-driven install flow describe Agent A's package as landed
(src/ghostreplay, console script ghostreplay) - verified present.

Known side effect to be aware of: running examples/run_demo.sh (or any
analyse) appends examples/sample_project/.ghostreplay-history.jsonl by
core design. The demo script says reports go to /tmp; the ledger line
is printed by the tool itself. The file was removed after verification
runs so the delivered examples tree is clean.

## Gates
Local only, stdlib only in all test/example code, no network calls,
nothing pushed, published, announced, or spent.
