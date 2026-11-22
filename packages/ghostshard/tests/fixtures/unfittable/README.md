# Fixture: unfittable

One file, `hub.py` (about 20k characters): a dispatcher, a registry
helper, and 24 helpers that all live in the same module. There is
no file-level seam to split on.

The test plans this fixture with a per-shard budget of 250
estimated tokens (via `--budget`), far below what even the
signatures slice of this file costs.

Expected planner behaviour (PLAN.md, Fit and limits):

- The plan must NOT present itself as a clean, complete, fitting
  plan. At least one honest signal must appear: a non-zero exit,
  the plan marked `partial`, or a shard carrying an unfittable
  flag/reason naming the budget problem.
- Nothing may be silently dropped to make the numbers fit.
