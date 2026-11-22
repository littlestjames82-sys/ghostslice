# Fixture: cycle

Two different cycles, two different expected behaviours.

## plan_folder/ - a shard dependency cycle (must FAIL check)

A hand-built plan folder in the exact `shards.json` schema the
planner writes, except `shard-a` depends on `shard-b` and
`shard-b` depends on `shard-a`. The per-shard bundles are valid
(hashes and token totals match the core estimator), so the ONLY
reason `ghostshard check plan_folder` may fail is the cycle.

Expected: exit code 1, and the output names a dependency cycle
including both shard ids. A cycle is a plan failure, never a
scheduling problem to solve at run time (PLAN.md).

## project/ - an import cycle in source (must NOT leak into a plan)

`a.py` imports `b.py` and `b.py` imports `a.py`. The planner
contracts strongly connected components into one shard unit, so
planning this project must yield a single shard owning both
files, and the resulting plan must pass `ghostshard check`.
