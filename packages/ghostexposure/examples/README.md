# GhostExposure examples

Everything here is invented sample material. No real code, no real data.

| File | What it is |
|---|---|
| `starter-surface.example.json` | A starter surface pack (auth, payments, config/secrets, personal-data shapes). Copy it and edit it for a real project. |
| `mini_project/` | A tiny project with one auth file and one unrelated helper, small enough to follow by hand. |
| `sample_EXPOSURE.md` | What the `EXPOSURE.md` in an exported bundle looks like, including both limit statements the plan requires. It is an illustration; a real export generates its own `EXPOSURE.md` from the actual scan. |

## Try it: scan, export, verify

Prerequisite: GhostExposure installed (`pip install .` from the repo root) or run from the repo root with `src/` on `PYTHONPATH`. No network access is needed.

Run from the repo root:

```bash
# 0. Read the pack you are about to apply.
ghostexposure packs --surface examples/starter-surface.example.json

# 1. Preview every file's decision. Nothing is written.
ghostexposure scan examples/mini_project --surface examples/starter-surface.example.json

# 2. Write the bundle to a new folder.
ghostexposure export examples/mini_project --surface examples/starter-surface.example.json -o /tmp/mini-bundle

# 3. Check the bundle the way a receiver would.
ghostexposure verify /tmp/mini-bundle
```

Expected shape of the result: `auth/login.py` is in the bundle as surface
(it matches the `auth/**` glob), `util/format.py` is accounted for as out,
and the bundle folder contains `files/`, `manifest.json`, `exposure.json`,
`EXPOSURE.md`, and `PROMPT.md`.

What to look at, in order:

1. The `scan` output: one line per file with its decision (`surface`, `context`, `out`, or `conflict`) and the reason codes that fired, then counts and the coverage limits. Scan exits with status `1` if any file is in conflict, `0` here.
2. `/tmp/mini-bundle/EXPOSURE.md`: the human summary a receiver reads first. Compare it with `sample_EXPOSURE.md` in this folder: same sections, generated from the real scan.
3. `/tmp/mini-bundle/exposure.json`: the per-file record. Find `util/format.py` listed with decision `out`; a file does not need to be in the bundle to be accounted for.
4. The `verify` output: it reports whether the bundle on disk matches its manifest and partition, then prints what verification cannot prove. That limit statement is part of every verification, not a warning about this sample.

## Make it yours

- Edit a copy of the surface pack, not the example: change a `pattern`, or add one with a new `id` and a plain-words `reason`, then re-run `scan` and watch which decisions change. The pack is data; the scan shows its effect file by file.
- Pin a file in or out for one project only by adding an `exposure` section to that project's `.ghostslice.json` (see the main `README.md`, "For senders", step 1). Pin a surface-matched file out and `scan` will list it as a `conflict` instead of deciding for you.
- Receiver practice: add any extra file under `/tmp/mini-bundle/files/` and re-run `verify`. It fails and names the added file. Remove the file and `verify` passes again. That is the whole check: the bundle on disk against the bundle its manifest records.
