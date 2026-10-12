# GhostSlice v0.1.0 — Build Report

Built Oct 12, 2026, per `PLAN.md`. Local build only: NOT published to
GitHub, PyPI, or npm (publishing is a separate Ryan gate).

## What was built

A zero-dependency (Python stdlib only), local-first tool that shows a
developer what a CLI agent will read before it runs:

- **Scanner** — walks a project, respects `.gitignore`, applies built-in
  ignores (`.git`, `node_modules`, `dist`/`build`/cache dirs, binary
  extensions and NUL-sniffed binaries), flags test files and lockfiles.
- **Token estimator** — documented BPE-like estimate (word/punctuation
  chunks, 1 token per chunk up to 4 chars then 1 per 4 chars). All counts
  everywhere are labelled estimates, never exact tokenizer counts.
- **AST slicer, modes: full / signatures / interfaces / strip-tests / exclude**
  - Python: real stdlib `ast`. Signatures keep imports, constants, and
    def/class signatures (decorators, first docstring line), no bodies.
    Interfaces keep classes, type aliases, Protocol-style defs.
    Strip-tests removes `test_*`/`Test*` by line range (rest byte-identical);
    a test file slices to empty.
  - TypeScript/JavaScript: parser-lite (regex + brace matching that
    starts at the real body brace, so `{}` parameter defaults work).
    Handles functions, arrow functions, classes/methods, interfaces,
    types, enums, and describe/it/test blocks.
- **Pre-flight cost estimator** — local, dated, editable `prices.json`
  (snapshot dated 2026-10-12, explicitly not live). Cost = input tokens.
- **Export** — `.claude_context` bundle: `manifest.json` (per file: path,
  mode, language, original tokens, sliced tokens, sha256 of the slice,
  plus totals), `files/` with the sliced sources, and `PROMPT.md`
  concatenating them with file headers. `ghostslice check` re-reads a
  bundle and verifies hashes and token totals against disk.
- **CLI** — `ghostslice scan|slice|export|check|serve|prices`, console
  entry point in `pyproject.toml`, `python -m ghostslice` also works.
- **Dashboard** — single-page local UI served by stdlib `http.server`
  (binds 127.0.0.1): files sorted by token cost with a heat bar, row
  click to include/exclude, per-file mode selector, live before/after
  totals, model selector with pre-flight $ before vs after, slice
  preview pane, and an Export button. Violet Ghost accent `#6716f3`.

## Files

```
pyproject.toml            ghostslice console entry point, zero deps
LICENSE                   MIT
README.md                 install/run docs + honest labels
prices.json               editable local price table (also packaged copy)
PLAN.md                   the plan this build followed
src/ghostslice/__init__.py, __main__.py
src/ghostslice/tokens.py      estimator + documented method
src/ghostslice/scanner.py     .gitignore-aware scanner
src/ghostslice/slicer.py      Python ast slicer + TS/JS parser-lite
src/ghostslice/pricing.py     prices loader + cost math
src/ghostslice/exporter.py    bundle build + validate
src/ghostslice/server.py      dashboard API (stdlib http.server)
src/ghostslice/dashboard.html single-page UI
src/ghostslice/cli.py         CLI
src/ghostslice/prices.json
tests/  (6 files, 48 tests)   tokens, scanner, slicer (py), slicer (ts),
                              pricing+export, server+CLI
```

## Verification (all run Oct 12, 2026)

- Tests: `PYTHONPATH=src python3 -m pytest tests -q` → **48 passed**.
  Also `PYTHONPATH=src python3 -m unittest discover -s tests` →
  **Ran 48 tests, OK** (unittest style, so the suite runs anywhere).
- Install: `pip install .` into a scratch target succeeded; the
  installed `ghostslice` console script ran a scan, and the installed
  package includes `dashboard.html` and `prices.json`.
- Server (live process, curl):
  - `GET /` → 200, dashboard HTML (7,857 bytes)
  - `GET /api/scan` → 42 files, 164,988 estimated tokens for GhostBus
  - `GET /api/prices` → local table with `as_of: 2026-10-12`
  - `GET /api/preview?path=src/core.mjs&mode=signatures` →
    14,232 → 2,195 estimated tokens (saved 12,037)
  - `POST /api/export` → `ok: true`, bundle written, totals match CLI

## Demo: real numbers on a real repo

Repo: `~/workspace/ghostbus` (GhostBus v0.5.10, TypeScript `.mjs` source),
scanned and sliced with GhostSlice itself. Estimated tokens throughout.

| Run | Before | After | Saved |
|---|---|---|---|
| `ghostslice scan` (whole repo, 42 files) | 164,988 | — | — |
| `ghostslice export` (default modes: signatures for code, strip-tests for test files, full for docs) | 164,988 | **53,339** | **111,649 (67.7%)** |
| `ghostslice slice --mode signatures` (signatures for all code, docs full) | 164,988 | 54,036 | 110,952 |
| Preview only: `src/core.mjs` signatures | 14,232 | 2,195 | 12,037 (84.6%) |

Pre-flight input cost at the local Claude Sonnet snapshot rate
($3.00/Mtok, prices.json dated 2026-10-12, not live):
**$0.4950 → $0.1600** per full-context run.

Notes on the demo: the single biggest file was the test suite
(`test.mjs`, 43,802 estimated tokens), which the export default removes
entirely via strip-tests; docs (CHANGELOG, hosted/security docs) stay
`full` under the defaults, so most of the remaining 53,339 is docs and
the signature surfaces. Bundle validation: `ghostslice check` → ok,
42 files checked, totals match a re-scan of the bundle.

## How to run

```bash
cd ~/workspace/ghostslice
PYTHONPATH=src python3 -m ghostslice scan ~/workspace/ghostbus
PYTHONPATH=src python3 -m ghostslice export ~/workspace/ghostbus -o /tmp/context-bundle
PYTHONPATH=src python3 -m ghostslice serve ~/workspace/ghostbus --port 8765
# dashboard: http://127.0.0.1:8765/
```

## Known limitations

- **Token counts are estimates.** The BPE-like estimator in `tokens.py`
  is not any model's exact tokenizer; use the numbers for relative
  pruning decisions, not billing.
- **Prices are a dated local snapshot** (2026-10-12) in `prices.json`.
  Edit that file to update; nothing is fetched and no rate is live.
- **TS/JS slicing is parser-lite**, not a real parser. Conventional
  shapes slice well (verified on GhostBus, including one-line methods,
  destructured parameters, and `{}` defaults); exotic syntax such as
  braces inside template literals or multi-line generics can slice
  imperfectly. Python slicing uses the real `ast` parser.
- **`.gitignore` support is the common subset** (negations, dir patterns,
  fnmatch globs); nested `.gitignore` files in subdirectories are not
  loaded, only the project root one.
- Dashboard Export writes the bundle inside the served project as
  `.claude_context/` (that directory is scanner-ignored).
- Only Python and TypeScript/JavaScript are sliced; other text files
  pass through as `full` (or `exclude`).

## Git

Local git repository initialised with the v0.1.0 tree committed.
Nothing pushed or published anywhere.
