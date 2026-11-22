# GhostLift examples

Small, runnable examples for each tier in README.md. Everything here
is stdlib-only Python and static analysis: no example runs the code
it lifts, and nothing here touches the network.

Run all commands below from the checkout root.

## Tier 1, exact recovery: `sourcemap_demo/`

- `originals/src/greeting.js` and `originals/src/math.js` are the
  original sources.
- `bundle.js` is the shipped, compact bundle and `bundle.js.map` is
  its source map. The map's `sourcesContent` holds the originals
  exactly, byte for byte.
- Exact recovery means: read the map, write the originals back out.
  The tests in `tests/test_sourcemap_recovery.py` and
  `tests/test_fixtures_static.py` pin that the map in this folder
  really does contain the originals unchanged.
- Run it with the core CLI:

```bash
PYTHONPATH=src python3 -m ghostlift lift examples/sourcemap_demo/bundle.js.map -o /tmp/lifted
diff examples/sourcemap_demo/originals/src/greeting.js /tmp/lifted/files/src/greeting.js
# No diff output: the recovery is byte-exact. That is what Tier 1 means.
```

## Tier 2, structured lift: `minified_demo/` plus `js_lift_demo.py`

- `app.min.js` is a minified file, `app.js` is a readable file with
  the same three functions (`clamp`, `describeScore`, `doubleIt`).
- Run it:

```bash
python3 examples/js_lift_demo.py
```

It prints the beautified, watermarked lift and the function
boundaries it found. The beautifier preserves tokens for the
fixture class it targets; its limits (regex literals, nested
template expressions) are stated in its module docstring.

## Tier 3, outline: `pyc_demo/` plus `pyc_outline_demo.py`

Do not confuse this demo with the core `.pyc` lift: for Python
bytecode the core CLI does a fuller Tier 2 structured lift
(signatures, docstrings, bytecode comments). This example shows the
thinner Tier 3 idea on the same kind of artifact: names and argument
lists only, rendered as labelled pseudo-source.

- `pyc_demo/sample_module.py` is a small Python module. No `.pyc` is
  shipped: the demo and the tests compile it at run time, because a
  `.pyc` only matches one Python version.
- Run it:

```bash
python3 examples/pyc_outline_demo.py
```

It prints a watermarked pseudo-source outline (function and class
names, argument names) recovered from the compiled bytecode. Only
run the `.pyc` demo on bytecode you produced yourself or trust. See
the safety note in `pyc_outline_demo.py` and in the main README.
