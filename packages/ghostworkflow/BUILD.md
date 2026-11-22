# BUILD.md - ghostworkflow v0.1.0 (Oct 18, 2026)

Built to the integration spec
(`~/workspace/ghostslice-companions/INTEGRATION_SPEC_DRAFT.md`,
Option A as decided by Ryan) and the evidence contract
(`~/workspace/ghostslice-companions/EVIDENCE_CONTRACT_DRAFT.md`).
Repository structure exactly as Ryan specified. Stdlib only,
version 0.1.0, nothing pushed or published.

## Final test line

```
45 passed in 4.58s
```
(`cd ~/workspace/ghostworkflow && PYTHONPATH=src python3 -m pytest
tests -q`; see RESULTS.md for the controlled run record.)

## Design choices

- **CLI-only integration.** Engines are invoked as subprocesses in
  argv form, never imported, per the spec. The orchestrator reads
  only what the engines print and the report files they write.
- **Engine discovery** (`adapters.py`): PATH console script first;
  then checkout trees. An explicit engine home (`--engine-home` or
  `GHOSTWORKFLOW_ENGINE_HOME`) replaces the default sibling search
  rather than adding to it, so a named home is authoritative and
  tests can be hermetic. Checkout invocation is
  `[sys.executable, "-m", <engine>]` with the tree's `src/` put
  first on PYTHONPATH. Versions are probed from each engine's own
  CLI; GhostBench has no `--version` flag (it errors), so the
  `version` subcommand is tried as well, and the first X.Y.Z in the
  output wins.
- **Verify verdicts are read from the report, not the exit code.**
  GhostVerify exits 1 for `gaps_found`, which the spec defines as a
  recorded outcome, not a crash. The step therefore keys on
  `verify-report.json`'s verdict: `sufficient` (with exit 0) is ok,
  `gaps_found` is attention, `could_not_verify` and anything
  unrecognized is failed, and a missing/unreadable report is failed
  whatever the exit code was. A `sufficient` verdict with a nonzero
  exit is explicitly not trusted as a pass.
- **Bench corpus.** Reuse is checked at
  `<project>/.ghostworkflow/corpus.json`, then
  `<project>/corpus.json`, and only counts when the corpus actually
  records this project (entry path resolves to the project dir).
  Creation is `ghostbench add` plus a starter task written into the
  corpus JSON in Bench's real corpus format (tasks nested under
  the project entry). The corpus deliberately lives outside the
  per-run output dir so runs reuse it.
- **Tree hash provenance.** The GhostSlice manifest carries no
  commit or tree hash (verified against its source), so the report
  takes `project_tree_hash` / `project_commit` from the Bench
  report's task rows, falling back to the corpus record's
  `tree_hash`, else `null` - with `tree_hash_source` stating which
  happened. Nothing is computed or invented by ghostworkflow
  itself.
- **Report validation** (`evidence.py`) is a focused checker for
  this schema's required fields, types, and enums, not a general
  JSON-Schema engine. When the shipped schema file is findable, the
  validator also asserts its `required` list agrees with the code.
  The CLI refuses to write a failing report and exits 1.
- **Levels.** A failed step's `verification_level` is normalized to
  `none` (it produced no evidence), and the run level is the
  strongest across ok/attention steps only.
- **Timeouts.** Each engine invocation has a per-step timeout
  (`--timeout`, default 600s); a timeout is a failed step with the
  reason recorded, not a hung run.

## Spec points implemented differently, and why

- **Corpus placement.** The spec says "create one via ghostbench
  add" without fixing a location; v0.1 puts the corpus at
  `<project>/.ghostworkflow/corpus.json` (stable across runs),
  while run outputs go to `<project>/.ghostworkflow/<run-id>/`.
  This is what makes the spec's "reuse an existing corpus"
  behavior real.
- **`--out` semantics.** The spec's `[--out <dir>]` is the run
  directory itself (board and report directly inside it), not a
  parent under which a run-id directory is created. Simpler to
  script against; the default (no `--out`) keeps the run-id
  namespacing.
- **Existing corpus with existing tasks.** If a reused corpus's
  project entry already has tasks, they are run as-is; a passed
  `--test-command` still adds `--run-tests` to the bench run but
  does not rewrite another corpus's tasks. Only the generated
  starter task is guaranteed to carry the given test command.

## Verified by hand, beyond the suite

A manual run against the real engines on a synthetic project
(`/tmp` shop example): exit 0, verdict `attention` (Verify found 2
real gaps; Bench recorded the task as failing while its contained
tests executed, level `tests-executed`), a real `sha256:` tree
hash from the Bench row with its source stated, `commit: null`
for a non-git project, engine versions probed as ghostslice 1.0.6
and 0.1.0 for the other three, and the resulting Console board
showing GhostVerify and GhostBench rows with
`level: tests-executed` - no Console adapter was needed, as the
spec predicted.
