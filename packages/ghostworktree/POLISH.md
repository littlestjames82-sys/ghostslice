# GhostWorktree v0.1 - Polish Round

Oct 14, 2026, at Ryan's "Polishing" direction. Sole folder owner for
this round. House loop: audit first, two improvement passes,
demonstrate-then-fix only. No version bump, no push, no publish.

Baseline: 36 tests passing (parent-verified). Final: **42 passed**
(36 existing, all still green, plus 6 new regression tests in
`tests/test_polish.py`), run by the polish owner:
`python3 -m pytest tests/ -q` -> 42 passed in 66.83s.

## Audit findings (each demonstrated against shipped v0.1 first)

- **A1, critical: create/cleanup registry race.** Two parallel
  creates given a single-port range (`--port-range 18211-18211`)
  both exited 0, both allocated port 18211, and the loser's
  registry record was overwritten and lost, leaving a worktree on
  disk that git knew and the registry did not. Cause: load ->
  allocate -> git -> save with no locking, last writer wins.
- **A2: status undercounts untracked work.** A new directory with
  3 untracked files reported `untracked=1, changed=1`. The
  `status_porcelain` docstring claimed `-uall` but the git call
  did not pass it, so git collapsed the directory to one entry.
  The dirty-cleanup refusal therefore understated how much
  uncommitted work `--force` would discard.
- **A3: `cleanup --delete-branch` misreported a safe outcome.**
  With an unmerged commit on the branch, cleanup removed the tree
  and the registry record, then exited 1 with git's last stderr
  line, which is the hint suggesting `git branch -D`, a command
  this tool deliberately never runs or recommends. Only the
  optional branch deletion had failed, and it failed safe (branch
  kept).
- **A4: malformed registry records crash with a traceback.** A
  record missing `path` made `list` die with a raw `KeyError`
  traceback. Corrupt JSON was handled with a named error; corrupt
  record shape was not validated at all.
- **A5: a failed registry save orphans the created tree.**
  Fault injection (registry save raising) left the worktree on
  disk with no registry record, and the raw `OSError` escaped the
  CLI's error handling (traceback), because `save()` re-raised it
  unwrapped.

Checked and found sound, no change: atomic registry replace,
corrupt-JSON named error, dirty refusal naming counts, branch kept
by default, duplicate name / duplicate port / branch checked-out
pre-checks, name validation, and the env rule (real `.env` never
read; nothing in this round touched `envcopy.py`).

## Pass 1: safety and correctness (A1, A2, A3, A5)

- `registry.py`: new `locked(root)` context manager, an exclusive
  `fcntl.flock` on `<root>/.registry.lock` (stdlib, POSIX; degrades
  to a no-op where `fcntl` is unavailable). `core.create` and
  `core.cleanup` hold it across the whole load -> allocate ->
  git -> save cycle. Reads stay unlocked: `save()` swaps the file
  atomically, so a reader always sees a complete old or new file.
- `core.py` create: after `git worktree add` succeeds, any failure
  in seeding/recording/saving rolls the brand-new tree back with a
  forced remove (safe: only env-example seeding has touched it)
  and re-raises, instead of orphaning it.
- `registry.py` save: write failures now raise `RegistryError`
  with the registry path, so the CLI reports them as a named
  error (exit 1) instead of a traceback.
- `gitops.py` status: `git status --porcelain=v1 -uall`, so every
  untracked file counts individually.
- `gitops.py` / `core.py` / `cli.py` branch deletion:
  `branch_delete_safe` raises a plain message that never echoes
  git's `-D` hint. Cleanup catches that refusal, records
  `branch_deleted: false` plus a new `branch_delete_error` field,
  and succeeds; the CLI prints `warning: branch <name> was kept: ...`.
  A refused safe delete is a warning, not a failed cleanup.

Verified by re-running the original demonstrations: the race now
produces one winner (exit 0) and one clean refusal (`no free port
in range`, exit 1) with exactly one record and one tree; the
untracked count is 3; the unmerged cleanup exits 0 with the
warning; the fault-injected create leaves no tree behind.

## Pass 2: robustness and CLI/README accuracy (A4)

- `registry.py` load: every record is validated (object with
  non-empty string `name`, `path`, `branch`, and an integer or
  null `port`). A bad record raises `RegistryError` naming the
  record index and the field, verified: `list` now exits 1 with
  `registry record #3 ... is missing a valid 'path' field` and no
  traceback.
- `cli.py`: `--delete-branch` help text now states the kept-branch
  warning behaviour.
- `README.md`: the dirty cleanup section documents the
  refused-delete warning outcome; the safety section documents the
  registry lock, create rollback, per-file untracked counts, and
  the malformed-record named error. `examples/demo.sh` was re-run
  end to end and still matches its documented output.

## Regression tests added (`tests/test_polish.py`, 6)

- `test_parallel_creates_get_distinct_ports_and_all_records_survive`
- `test_parallel_creates_single_port_range_exactly_one_wins`
- `test_status_counts_every_untracked_file_in_a_new_directory`
  (also pins the refusal message's entry count)
- `test_cleanup_delete_branch_unmerged_is_a_warning_not_a_failure`
  (also asserts the output never suggests `branch -D`)
- `test_malformed_registry_record_fails_named_without_traceback`
- `test_create_rolls_back_the_tree_when_registry_save_fails`

## Deliberately left alone

- **Port bind check is IPv4 localhost only, at create time.** A
  service bound only on IPv6, or a port in TIME_WAIT, can still
  surprise allocation. Documented v0.1 limit in PLAN.md/README;
  widening it was not backed by a demonstrated user-facing failure
  in this tool's own workflow.
- **`--path` may place a tree inside the repo.** Explicit user
  choice; the tool only forbids the main checkout itself.
- **No fsync of the registry file or its directory.** The atomic
  replace already prevents torn reads; durability against an OS
  crash mid-write is beyond the demonstrated failure set.
- **Registry `schema` value is not enforced.** Records are now
  validated, which covers the demonstrated crash; a schema
  migration policy is a v0.2 decision, not a polish fix.
- **Unmerged (`UU`) status entries count as both staged and
  unstaged.** Matches git's own two-column porcelain semantics;
  the total and the dirty verdict, which cleanup relies on, are
  correct.

## Gates held

Stdlib only (the lock uses `fcntl`, guarded), local only, no
network, no version bump, no push, no PyPI/publish, no
announcements, no spend. No folder other than
`~/workspace/ghostworktree/` was touched. The real `.env` rule is
unchanged and absolute.
