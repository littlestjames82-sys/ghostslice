# Fixture: shared symbol

`report.py` and `export.py` both import `normalize_records` from
`shared_core.py`. The task file pre-splits the work into two
subtasks (report view, export view), and both subtasks touch the
shared symbol.

Expected planner behaviour (verification bar, PLAN.md):

- `shared_core.py` / `normalize_record(s)` is OWNED by exactly one
  shard. Never two owners.
- The other shard is either sequenced after the owner (a
  `depends_on` edge) with the shared file present as read-only
  signatures context, OR the plan names the collision in its
  conflicts list.
- The two shards must not be presented as freely parallel with no
  edge and no conflict.
