# Fixture: disjoint

Two independent Python modules, `alpha/alpha.py` and
`beta/beta.py`, with no imports, calls, or shared symbols between
them. They live in separate top-level packages on purpose: the
planner merges lone files that share one package into a single
miscellaneous shard, so a flat layout would hide the very
disjointness this fixture exists to prove.

Expected planner behaviour (verification bar, PLAN.md):

- Planning against `TASK.txt` (or the same string via `--task`)
  yields two shards, one owning `alpha/alpha.py`, one owning
  `beta/beta.py`.
- Both shards sit in ONE parallel group; max parallelism is 2.
- Zero files are owned by more than one shard, and there are no
  shared-owned files between the two shards.
