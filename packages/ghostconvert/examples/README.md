# GhostConvert examples

One small bundle, converted to all four targets. If you have no
GhostSlice bundle of your own yet, start here: everything below runs
against the sample bundle committed in this directory.

Try it in two commands, from the GhostConvert checkout:

```sh
# Summarise the sample bundle, writing nothing
PYTHONPATH=src python3 -m ghostconvert inspect examples/sample_bundle

# Convert it for AGENTS.md readers, into a scratch directory
PYTHONPATH=src python3 -m ghostconvert convert \
  examples/sample_bundle --to agents -o /tmp/ghostconvert-demo
```

The inspect summary for this bundle reads, in part:

```text
Project: sample_project
Sliced by: ghostslice 1.0.6 (preset: claude-code)
Files: 7 (5 with bodies, 1 emptied by GhostSlice, 1 excluded)
Totals: 211 sliced of 287 original estimated tokens (method: ...)
Emptied by GhostSlice (no body by design): tests/test_app.py (mode: strip-tests)
```

(The token method string is longer in the real output; it is quoted
from the manifest, not computed by GhostConvert.)

## What is here

- `sample_project/` - a tiny demo project. Its `.ghostslice.json`
  profile asks GhostSlice for mixed modes: `src/app.py` in full,
  `src/util.py` as signatures only, `vendor/` excluded, tests stripped
  by Slice's defaults.
- `sample_bundle/` - the GhostSlice bundle exported from that project
  (`manifest.json`, `PROMPT.md`, and `files/`). This is the input
  GhostConvert reads. It is never modified by conversion.
- `converted/` - the output of one `ghostconvert convert --to all` run
  on that bundle:
  - `converted/agents/AGENTS.md`
  - `converted/cursor/.cursor/rules/*.mdc` (one rule file per top-level
    directory: src, docs, and root)
  - `converted/copilot/.github/copilot-instructions.md`
  - `converted/generic/prompt.md`
  - a `LOSSES.md` next to each target's artifact, naming what that
    format could not carry (the excluded `vendor/blob.py`, per-file
    hashes, per-file token estimates, and more)

## Regenerate it yourself

From the GhostSlice checkout:

```sh
PYTHONPATH=src python3 -m ghostslice export \
  path/to/ghostconvert/examples/sample_project \
  -o path/to/ghostconvert/examples/sample_bundle
```

Then from the GhostConvert checkout:

```sh
PYTHONPATH=src python3 -m ghostconvert convert \
  examples/sample_bundle --to all -o examples/converted --force
```

(`--force` because the converted outputs already exist here.)

## Things worth noticing in the output

- File order inside every artifact is the manifest's order, not
  alphabetical order.
- `src/util.py` arrives as signatures in every target, because that is
  what Slice put in the bundle. Its section header says
  `(mode: signatures)`, which is the warning.
- `tests/test_app.py` was stripped by Slice to an empty body, so it has
  no section anywhere. It is named in every `LOSSES.md` instead of
  vanishing quietly.
- `vendor/blob.py` appears in no artifact at all. It is named in every
  `LOSSES.md` under excluded files.
