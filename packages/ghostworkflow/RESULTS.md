# GhostWorkflow - Test Results

Reproducible record of a full-suite run. Regenerate on every
release-grade change; counts quoted anywhere else must match this
file or be removed.

## Run of Oct 18, 2026 (v0.1.0 build)

- Date (UTC): 2026-10-18T21:09Z
- Platform: Linux 7.0.0-39-generic x86_64
- Python: 3.12.3
- pytest: 9.1.1
- Tree: ghostworkflow v0.1.0, initial build (orchestrator, evidence
  contract validation, fake-engine sanity gate, one real
  end-to-end run through the four sibling engines)
- Command:

```sh
cd ghostworkflow
PYTHONPATH=src python3 -m pytest tests -q
```

- Result: **45 passed** (4.58s), 0 skipped, 0 failed

## What the suite covers

- `tests/test_pipeline.py` (5): happy path over fake engines
  (report validates, board written, contract fields populated);
  `--test-command` raises the bench step and the run to
  `tests-executed`; an existing corpus is reused, not re-created;
  usage error exits 2; and one real end-to-end run of a synthetic
  mini project through the real GhostSlice, GhostVerify, GhostBench
  and GhostConsole checkouts (siblings of this repo), asserting the
  workflow report validates, the board exists, and the bench
  evidence reaches `tests-executed` when a test command is passed.
- `tests/test_failures.py` (7): a `gaps_found` Verify verdict is
  attention with run exit 0; `could_not_verify` is a failure; a
  Slice engine failure marks Verify and Bench skipped while Console
  is still attempted and the report is still written (exit 1); a
  Bench nonzero exit is a failure; Bench failing tasks are
  attention; a missing Verify report is a failure; a missing engine
  is an honest failed step naming what was searched.
- `tests/test_evidence.py` (33): the report validator (every
  required field, bad verdicts/levels/provenance, per-step types,
  the engines map), level ordering, the shipped JSON Schema's
  agreement with the validator, `write_report` refusing an invalid
  report, and tree hash staying `null` with an "unavailable" source
  when no engine records one.

## Skips

None in this run. The real end-to-end test skips with a stated
reason only when a sibling engine checkout is genuinely absent;
all four were present here.
