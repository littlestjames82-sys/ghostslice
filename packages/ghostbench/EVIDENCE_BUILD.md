# EVIDENCE_BUILD.md - GhostBench half of the shared evidence contract

Built Oct 18, 2026 in the real tree (`~/workspace/ghostbench`), from
`~/workspace/ghostslice-companions/EVIDENCE_CONTRACT_DRAFT.md` (Bench
sections). Version stays 0.1.0. Stdlib only. No existing test was
weakened or deleted; 23 tests were added. Nothing pushed or
published.

## Sanity gate: known-answer probes (run BEFORE any code change, then re-run after)

Probe set (encoded permanently as tests in
`tests/test_evidence_contract.py`; the ad-hoc probe scripts were run
against `ghostbench.runner._run_test_in_temp` directly):

| # | Probe | Pre-fix result | Post-fix result |
|---|-------|---------------|-----------------|
| 1 | Normal passing test command in the temp copy | `pass` | `pass` |
| 2 | Failing test command (exit 3) | `fail` | `fail` (exit_code 3) |
| 3 | `GHOSTBENCH_PROBE_SECRET` planted in parent env; test command dumps its environment | **LEAKED**: output contained `SECRET_IS: probe-secret-value-12345` | **Not leaked**: output is `SECRET_IS: ABSENT`; HOME points inside the per-run temp area; PATH still present |
| 4 | Patch touching `../../gb-evidence-escape.txt` | No file created, but only because git 2.43 itself refused it (`error: invalid path`). GhostBench had NO validation of its own; containment depended entirely on the local git binary. Headerless absolute-path patches were silently rewritten by git (leading slash stripped) and applied inside the copy | **Refused by Bench's own validator BEFORE git apply**: status `patch-apply-failed`, detail `patch refused (containment): patch path escapes the temporary copy: '../../gb-evidence-escape.txt'`; no file created. Headerless absolute paths and write-through-a-patch-created-symlink variants are also refused by the validator |
| 5 | Project file `link.txt` is a symlink to a file outside the project; test reads it | **LEAKED**: copytree followed the link; test output contained the outside file's content (`PROBE-OUTSIDE-CONTENT-6789`) | **Not leaked**: link skipped, test sees no such file; result records `skipped_symlinks: ["link.txt"]` in both the result and its `sandbox` block |

Additional post-fix behaviour confirmed by tests: a symlink to a file
INSIDE the project is still copied as before; a dangling symlink is
skipped and recorded instead of crashing the copy (pre-fix copytree
would raise); a legitimate patch still applies, the test runs the
patched content, and the original project tree is byte-unchanged.

## What was implemented

### 1. Contained test execution (`src/ghostbench/runner.py`)

- **Scrubbed environment** (`_scrubbed_env`): allowlist only (PATH,
  LANG/LC_*, SystemRoot/WINDIR/COMSPEC/PATHEXT where present);
  HOME set to the temp copy, TMPDIR/TEMP/TMP to the per-run temp
  dir. The parent environment is never inherited wholesale.
- **Patch containment** (`_validate_patch_paths`, GhostVerify
  `patch.py::_safe_target` pattern): every path in the patch
  (diff --git, ---, +++ headers, including headerless diffs) is
  resolved against the resolved temp-copy root before `git apply`;
  `../`, absolute, symlinked-parent, and through-a-patch-created-
  symlink escapes are refused with status `patch-apply-failed` and
  a detail starting `patch refused (containment):`. Symlink entries
  a patch creates (mode 120000) whose targets resolve outside the
  copy are refused too. `git apply` remains a second line of
  defence, no longer the only one.
- **Copied-tree symlink check** (`_copy_project_safely`): a symlink
  whose target resolves outside the project (or dangles) is skipped
  and recorded as `skipped_symlinks` on the test result and inside
  its `sandbox` block; inside-pointing symlinks copy as before.
- **Resource limits**: POSIX `resource` via `preexec_fn` -
  RLIMIT_CPU 110s, RLIMIT_FSIZE 64 MiB, RLIMIT_AS 2 GiB,
  RLIMIT_CORE 0. Existing 120s wall timeout kept; captured output
  capped at the last 1000 characters (now a named constant).
- **Honest `sandbox` block** on every executed/attempted test
  result, and at report level when any row ran tests:
  `enforced` lists the six items above; `not_enforced` states
  plainly that host filesystem writes by the test process are NOT
  prevented (it runs with the user's permissions, no OS sandbox),
  network access is NOT blocked or monitored, and rlimits are
  best-effort POSIX only.

### 2. verification_level (evidence contract field)

- Enum `none < static-analysis < tests-executed < live-agent`
  (`VERIFICATION_LEVELS`, `strongest_verification_level`).
- Per task row in `run_task`: tests actually ran in the contained
  runner -> `tests-executed`; otherwise any static evidence (tokens
  measured, recorded patch scored, Verify/symbol signals) ->
  `static-analysis`; a row over an empty/unreadable project that
  measured nothing -> `none`. Never inflated.
- Report level in `run_corpus` = strongest row level. Report also
  gains `provenance: "live"` and the report-level `sandbox` block.
  `honest_scope.tier` now matches the level (a tests-executed run no
  longer calls itself "static"), and when tests were not run the
  `what_was_not_measured` list says so. The ledger record carries
  the level too.

### 3. BENCH.md first screen (`src/ghostbench/report.py`)

- First lines now carry `- Verification level: <level> - <plain
  words>` (e.g. "static analysis only (no tests executed, no live
  agent run)") directly under the Tier line, before any task detail.
- Sample reports render `# *** SAMPLE REPORT - NOT A REAL RUN ***`
  as the literal first line, with the sample note, when the report's
  `sample` flag is set.
- A "Test execution containment" section prints the sandbox
  enforced / not-enforced lists whenever the report carries one.
- The per-task table gained a `Level` column.
- The two shipped sample reports
  (`examples/runs/sample-tier-a-run-{a,b}/bench-report.json`) gained
  `verification_level: static-analysis` (top level and per row) and
  `provenance: sample`, and their BENCH.md files were re-rendered
  through the new renderer so the shipped examples are
  contract-shaped. Pre-contract reports rendered through the new
  code show the level as "not recorded (pre-contract report)"
  rather than inventing one.

## Files changed

- `src/ghostbench/runner.py` - contained runner (env scrub, patch
  validation, safe copy, rlimits, sandbox block), verification_level
  derivation (row + report), honest_scope consistency, ledger field.
- `src/ghostbench/report.py` - first-screen verification level in
  plain words, SAMPLE banner, containment section, per-task Level
  column.
- `tests/test_evidence_contract.py` - NEW, 23 tests (probes 1-5,
  sandbox block, output cap, rlimits, patch variants, legit-patch
  regression, symlink variants, level ordering/derivation,
  BENCH.md first-screen and banner rendering).
- `examples/runs/sample-tier-a-run-a/bench-report.json` +
  `BENCH.md`, `examples/runs/sample-tier-a-run-b/bench-report.json`
  + `BENCH.md` - contract fields added; BENCH.md re-rendered.
- `EVIDENCE_BUILD.md` - this file.

## Final test run

```
$ cd ~/workspace/ghostbench && PYTHONPATH=src python3 -m pytest tests -q
92 passed, 1 skipped in 3.11s
```

Baseline was 69 passed, 1 skipped; 69 + 23 new = 92. The 1 skip is
the pre-existing documented skip (budget-cap stop reachable only
through an injected executor the CLI does not expose).

## Limitations (could not implement as specced, and why)

1. **Host-write and network containment are NOT OS-enforced.**
   Pure-stdlib Python cannot put a child process in a real sandbox
   portably (no namespaces/seccomp from the stdlib on this
   platform). The implementation contains what it can (env, cwd,
   copy, patch paths, rlimits, timeout) and the report states the
   rest in `sandbox.not_enforced` rather than claiming a sandbox
   that does not exist - per the spec's honesty requirement.
2. **`live-agent` is defined but never emitted yet.** Tier B in
   v0.1 has no report writer (`run_live` returns an injected
   executor's dict unchanged and the built-in executor refuses), so
   no code path can honestly produce a live-agent report today.
   The enum, ordering, and BENCH.md wording for it are in place for
   when Tier B lands.
3. **Patch parsing is best-effort for exotic diffs.** Standard
   unified diffs (with `diff --git` headers and headerless) are
   fully parsed. Paths containing spaces are taken whole from the
   ---/+++ lines, but a `diff --git` line with space-containing
   paths is ambiguous by format; quoted diff paths are unquoted
   before checking. A path the parser somehow missed still faces
   `git apply`'s own checks, and the copied tree contains no
   escaping symlinks for it to write through.
4. **RLIMIT_AS (2 GiB)** could refuse a legitimately huge test
   process; it is a stated, deliberate cap, listed under enforced
   limits, not a silent one.
5. **RESULTS.md (spec section "Reproducible results") was not
   created** - it is step 3 of the contract build order, shared
   with the GhostConsole half, and outside this task's deliverables
   (sandbox + verification_level + BENCH.md).
