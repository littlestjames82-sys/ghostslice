# GhostDeps examples

Two small fixture projects with gaps planted on purpose, so you can see
exactly what a pack does with each kind of mismatch. Neither project
needs its dependencies installed; GhostDeps reads files, it never runs
or installs anything.

The commands below assume you run them from this `examples/` directory
and that `ghostdeps` is on your PATH (see the install notes in the top
level README; from a source checkout without installing, use
`PYTHONPATH=../src python3 -m ghostdeps` in place of `ghostdeps`).
Output directories (`out-python`, `out-node`) are created for you and
are safe to delete afterwards; the example projects themselves are
never modified.

Both examples exit 1 under `doctor` and `pack`, on purpose: each one
plants an imported-but-not-declared package, and that is the one
finding that sets exit code 1. A project whose declarations and
imports line up exits 0, and the planted "declared, not imported"
entries below are the reason neither example exits 1 on their account:
that section is information, not a finding.

## python_project

- `pyproject.toml` declares requests, colorama, and Pillow.
- `requirements.txt` pins requests 2.31.0, colorama 0.4.6, Pillow 10.2.0.
- `app.py` imports requests and PIL (the import name for Pillow), plus
  numpy, which is declared nowhere. It also imports `os` (standard
  library) and a local `helper` module.

Run:

```
ghostdeps pack python_project -o out-python
ghostdeps doctor python_project
```

What to look for in `out-python/DEPS.md`:

- Declared and used: requests and Pillow.
- Declared, not imported: colorama, worded as "no import found in
  scanned code", with possible innocent explanations listed. It might
  be a command line entry point or a plugin; the pack does not guess.
- Imported, not declared: numpy, with `app.py` named as the evidence.
- Pins as recorded: the three exact versions from `requirements.txt`.
- Doctor exits 1, because imported-not-declared is a finding.

## node_project

- `package.json` declares express and lodash, plus typescript as a
  dev dependency.
- `package-lock.json` pins express 4.18.2 and lodash 4.17.21, padded
  with transitive entries so you can compare sizes: the lockfile is
  several thousand lines of machine data in a real project, and the
  pack summarises it instead of copying it.
- `index.js` requires express and axios. Axios is declared nowhere.
  The `./util` require is a local file, not a package.

Run:

```
ghostdeps pack node_project -o out-node
ghostdeps doctor node_project
```

What to look for in `out-node/DEPS.md`:

- Declared and used: express.
- Declared, not imported: lodash and typescript.
- Imported, not declared: axios, with `index.js` named as evidence.
- Pins as recorded: 4.18.2 and 4.17.21, exactly as the lockfile has
  them.
- The pack files together are smaller than the raw lockfile.

JavaScript and TypeScript import extraction is parser-lite (pattern
matching over import and require statements), and every report labels
it that way. Python imports are read with the real `ast` parser.

## Reading the machine-readable pack

Each pack also writes `deps-manifest.json` next to `DEPS.md`, with the
same facts plus the per-entry evidence. To browse it:

```
python3 -m json.tool out-python/deps-manifest.json | head -n 60
```

The keys worth knowing first are `sections` (the four report sections),
`counts` (the summary numbers), `sources` (every manifest or lockfile
found, and whether it was parsed or only detected), and `source_groups`
(the same sources grouped by the directory that holds them).
