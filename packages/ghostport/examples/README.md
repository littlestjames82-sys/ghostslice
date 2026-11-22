# GhostPort examples

- `demo_project/` - a tiny unmigrated legacy Python project (3 files,
  3 pattern hits, a real dependency chain). Start here.
- `fixture/` - a larger sample project (`src/pkg/` with an ordering
  chain plus a two-node import cycle, and a covering test) of the kind
  the test suite uses. Useful for seeing how a cycle is combined into
  one unit.
- `sample_port_plan/` - illustrative samples of what `plan` and `bundle`
  write (`PORT_PLAN.md`, `port-plan.json`, a `UNIT.md` checklist). These
  files are hand-written samples of the format, clearly labelled, not
  generated output. Field names in a real `port-plan.json` are the ones
  the core writes (for example `depends_on_units`, not `depends_on`);
  trust a real run over the sample when they differ.
- `ghostslice-profile-snippet.json` - the `port` section a project adds
  to its `.ghostslice.json` (pack choice, per-unit budget, manual
  merge/reorder for dynamic-call cases the static graph can miss, as
  called out in PLAN.md). The keys in the snippet are exactly the keys
  the loader accepts; any other key in the `port` section is an error.

## Walkthrough

Works with an installed `ghostport`, or from the repo root with
`PYTHONPATH=src python3 -m ghostport` in place of `ghostport`.

`scan` writes nothing, so it is safe to run against the demo in place.
`plan`, `bundle`, `claim`, and `verify` do write: a plan and a ledger
(`.ghostport-history.jsonl`) inside the project, and bundle files at
the `-o` path. To keep the checked-in demo pristine, copy it first:

```bash
cp -r examples/demo_project /tmp/demo_project

ghostport scan  /tmp/demo_project --pack python-upgrade
# Expected: 3 hits - PYUP004 (legacy/plugin_loader.py), PYUP003
# (legacy/report.py), PYUP006 (legacy/storage.py); 4 Python files
# scanned, 1 with zero hits.

ghostport plan  /tmp/demo_project --pack python-upgrade
ghostport bundle /tmp/demo_project --unit unit-legacy-storage -o /tmp/port-unit-legacy-storage
ghostport status /tmp/demo_project

# After a person or agent has ported the unit (GhostPort never does):
ghostport claim  /tmp/demo_project --unit unit-legacy-storage --by your-name
# After GhostVerify has checked the ported unit and written a report:
ghostport verify /tmp/demo_project --unit unit-legacy-storage --report /path/to/ghostverify-report.json

ghostport packs --pack python-upgrade
```
