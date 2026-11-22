# GhostPacks examples

Two things to run by hand, from the repo root, with no network:

## 1. The demo pack

`demo-python-pack/` is a complete, valid, deliberately unscored
pack. Check it and look at it:

```bash
PYTHONPATH=src python3 -m ghostpacks lint examples/demo-python-pack
PYTHONPATH=src python3 -m ghostpacks show examples/demo-python-pack
```

`lint` should pass (`lint: OK - demo-python 0.1.0 (kind: context,
unscored) [python]`). `show` should print the word **unscored** in
the summary: the pack claims no GhostBench number, so it may not
borrow one. `PYTHONPATH=src python3 -m ghostpacks doctor
examples/demo-python-pack` runs the wider checks (GhostSlice range,
freshness, Bench status) and reports the same unscored state as a
warning, not a failure.

## 2. Merge, then remove, on the fixture project

`fixture-project/` is a two-file Python project with a baseline
`.ghostslice.json` (no ignores, no modes). Work on a copy so the
example stays pristine:

```bash
cp -r examples/fixture-project /tmp/packs-demo-project

PYTHONPATH=src python3 -m ghostpacks merge examples/demo-python-pack /tmp/packs-demo-project
# read the preview diff, answer y
# (add --yes to either command to skip the prompt; the diff is still printed)

cat /tmp/packs-demo-project/.ghostslice.json      # src/** is now signatures, generated/** ignored
cat /tmp/packs-demo-project/.ghostslice-packs.json  # provenance lockfile entry for demo-python 0.1.0

PYTHONPATH=src python3 -m ghostpacks remove /tmp/packs-demo-project demo-python

cat /tmp/packs-demo-project/.ghostslice.json      # back to the baseline, byte for byte
```

That round-trip is the suite's core promise, and
`tests/test_merge_remove_roundtrip.py` runs the same flow through
the real GhostSlice exporter and compares manifest totals before and
after.

## 3. A Bench report template

`bench-report.template.json` shows the shape of the report file a
pack must contain before it may claim a score in `pack.json`
(`"bench": {"score": N, "report": "bench-report.json"}`).
It lives outside any pack folder on purpose: a report only counts
when it is inside the pack that references it and records a real
GhostBench Tier A run on a stated reference project.
