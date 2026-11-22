# GhostWatch examples

A runnable walkthrough on a tiny fixture project. Everything is
local; nothing here is published or sent anywhere.

Each numbered step shows the command and the verdict or exit code
to expect, so you can tell at a glance whether your run matches.
Note what the walkthrough never does: no step refreshes the
bundle behind your back. The only step that even attempts a
re-export is step 7, where `--reexport` is passed explicitly,
and it is there to show the graceful failure when GhostSlice is
not installed.

## Layout

- `fixture-project/` - two-file Python project (`src/app.py`,
  `src/util.py`) with a baseline `.ghostslice.json` profile.
- `fixture-bundle/` - a GhostSlice-shaped bundle for that project:
  `manifest.json` (per-file `sha256` is the hash of the *sliced*
  text in `files/`, exactly as a real GhostSlice manifest),
  `PROMPT.md`, and `files/src/...`. `src/app.py` is sliced `full`;
  `src/util.py` is `signatures` with `symbols_included: ["slugify"]`.
- `demo-pack/` - a data-only GhostPacks-shaped Pack (`pack.json` +
  `profile.json`) whose `bundle` points at `../fixture-bundle`.
  GhostWatch checks a Pack's bundle exactly the way it checks any
  bundle, and reports the verdict as the Pack verdict
  (`pack_stale` mirrors `stale`).

## Walkthrough

From the repo root:

```bash
export PYTHONPATH=src

# 1. Snapshot the fixture project at bundle time.
#    (Writes fixture-project/.ghostwatch/snapshot.json - hashes and
#    symbol names only, no file bodies. Delete that folder to reset
#    the walkthrough.)
#    Expected output, abbreviated:
#      [ghostwatch] snapshot: 3 file(s) hashed -> examples/fixture-project/.ghostwatch/snapshot.json
python -m ghostwatch snapshot examples/fixture-project --bundle examples/fixture-bundle

# 2. Check once: nothing has changed, so the verdict is fresh (exit 0).
#    Expected output:
#      [ghostwatch] verdict: fresh (baseline: snapshot)
python -m ghostwatch check examples/fixture-project --bundle examples/fixture-bundle
echo $?

# 3. Check the demo Pack's bundle the same way.
python -m ghostwatch check examples/fixture-project --bundle examples/fixture-bundle --json | grep pack_stale

# 4. Make the bundle stale: edit a bundled file's body.
#    Expected output:
#      [ghostwatch] verdict: stale (baseline: snapshot)
#        changed_in_bundle: 1
#          - src/app.py: content changed since snapshot
printf '\n# drift\n' >> examples/fixture-project/src/app.py
python -m ghostwatch check examples/fixture-project --bundle examples/fixture-bundle
echo $?   # 1 = stale, src/app.py named under changed_in_bundle
python -m ghostwatch check examples/fixture-project --bundle examples/fixture-bundle \
  --json-out /tmp/watch-report.json --md-out /tmp/WATCH.md

# 5. Touch is not stale: remove the "# drift" line added in step 4
#    (or restore the file from a clean copy), re-snapshot, touch it.
python -m ghostwatch snapshot examples/fixture-project --bundle examples/fixture-bundle
touch examples/fixture-project/src/app.py
python -m ghostwatch check examples/fixture-project --bundle examples/fixture-bundle
echo $?   # 0 = fresh; src/app.py appears under touched_only

# 6. No-baseline behaviour: delete the snapshot and check again.
#    The verdict is unknown (exit 2), never a confident fresh, and
#    the report names the manifest_heuristic baseline.
rm -rf examples/fixture-project/.ghostwatch
python -m ghostwatch check examples/fixture-project --bundle examples/fixture-bundle --json | grep -E 'verdict|baseline'
echo $?

# 7. Graceful re-export failure: make it stale, then ask for
#    --reexport on a machine without GhostSlice. Watch reports
#    "reexport: unavailable", keeps the stale verdict, exits 1,
#    and writes nothing.
printf '\n# drift again\n' >> examples/fixture-project/src/app.py
python -m ghostwatch check examples/fixture-project --bundle examples/fixture-bundle --reexport
echo $?

# 8. Polling loop (bounded for the demo): re-snapshot first so the
#    baseline matches, then watch for a few polls and edit a file
#    in another terminal to see the settled stale verdict print.
python -m ghostwatch snapshot examples/fixture-project --bundle examples/fixture-bundle
python -m ghostwatch watch examples/fixture-project --bundle examples/fixture-bundle \
  --interval 1 --max-polls 5
```

Restore the fixture when you are done: remove the appended drift
lines from `fixture-project/src/app.py` and delete
`fixture-project/.ghostwatch/`.
