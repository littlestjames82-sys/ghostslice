# GhostFixture v0.1 - Implementation Notes (Agent A, core)

Built Oct 14, 2026. Ownership respected: PLAN.md, src/**, pyproject.toml,
IMPLEMENTATION_A.md only. tests/**, README.md, examples/** untouched.

## Delivered

- [PLAN.md](PLAN.md) - written first, in GhostSlice plan format (why this
  name, problem, position in the stack, MVP, out of scope, build estimate,
  pricing draft marked not public and not decided, verification bar, risks,
  next gate). No em dashes.
- [pyproject.toml](pyproject.toml) - ghostfixture 0.1.0, zero dependencies,
  console script `ghostfixture`.
- `src/ghostfixture/bundle.py` - GhostSlice bundle reader. Referenced set =
  manifest entries whose mode is not `exclude`; excluded paths are tracked
  separately because the exclusion is binding (see below). Malformed manifest
  raises BundleError, which the CLI maps to exit 2, never to an empty fixture.
- `src/ghostfixture/secrets.py` - secret shape scan applied before copying:
  private-key headers, AWS access keys, GitHub tokens, OpenAI/Anthropic keys,
  Slack tokens, Google API keys, Stripe keys, password-bearing URLs, plus
  sensitive-name assignments gated by placeholder and entropy checks.
  Findings are pattern type strings only; no value is ever recorded.
- `src/ghostfixture/closure.py` - static local import closure. Python via
  real `ast` (absolute imports resolve from project root, then the importing
  file's directory; relative imports against the file's package; package
  `__init__.py` chain included). JS/TS via import/export-from/require/
  dynamic-import patterns, relative specifiers only, extension and index
  resolution. Bare specifiers are returned as external references.
- `src/ghostfixture/build.py` - build + check.
  - Per candidate, in order: bundle-exclusion bar, existence, symlink/root
    containment (realpath inside project root; links never followed out),
    secret shape scan, then the total size cap (default 2 MiB, stated in CLI
    output and in the manifest). Bundle-referenced files are served first in
    manifest order; closure files after in BFS order.
  - Copies are the ORIGINAL project files at full fidelity, never the sliced
    bundle text. Output must not be inside the project and the project must
    not be inside the output; an existing non-empty output dir is refused.
    The source project is only ever read.
  - `check` re-verifies sha256 of every included file, absence of
    excluded-flagged files, and no unrecorded extra files. `__pycache__`
    and .pyc/.pyo files are treated as runtime byproducts (a fixture exists
    to be run) and are listed as ignored, not as tampering.
- `src/ghostfixture/reports.py` - FIXTURE.md rendering of the manifest.
- `src/ghostfixture/mcp_server.py` - stdio JSON-RPC: `build_fixture`,
  `check_fixture`, summary payloads capped at 50 items, no file bodies.
- `src/ghostfixture/cli.py` - `build` / `check` / `mcp`. Exit codes: build
  0 built (exclusions are reported outcomes, not failures), 1 fixture would
  be empty, 2 could not build; check 0 clean, 1 mismatch, 2 could not check.

Fixture manifest keys: task, source_project, source_bundle,
source_bundle_manifest_sha256, generated_at, max_bytes, include_flagged,
totals (files_considered / files_included / files_excluded_flagged /
files_left_out / bytes_copied), included[] (path, reason
bundle-referenced|import-closure, via, bundle_mode, bytes, sha256),
excluded_flagged[] (path, types, optional included_by_override),
left_out[] (path, reason, detail), external_references[],
closure_by_language, limits[].

Left-out reasons: bundle-excluded, missing-in-project,
symlink-escapes-root, outside-root, unreadable, size-cap.

## Design decisions worth knowing

1. Bundle exclusions are binding. If the bundle lists a file with mode
   `exclude`, Fixture never copies it, even when a copied file imports it
   (recorded as left out, reason `bundle-excluded`). Closure only adds
   files the bundle never mentioned. This matches the PLAN text and Agent
   B's test contract, and it keeps Slice-level decisions (profile excludes,
   secret excludes) from being silently undone by the closure.
2. Copies are originals, not sliced text. The bundle decides which files;
   the project supplies the bytes. The manifest records the bundle manifest
   sha256 so the pairing is auditable if the project moved on afterwards.

## Fixes driven by Agent B's suite (5 initial failures, all fixed core-side)

- Manifest key names aligned to the suite contract: source_project,
  source_bundle, source_bundle_manifest_sha256 (were project, bundle,
  bundle_manifest_sha256).
- Stripe key shape (`sk_live_` / `sk_test_` / `rk_`) added to the on-sight
  provider patterns. B's canary file was slipping through: the value
  contains the word "fixture", which correctly suppresses the generic
  assignment path as a placeholder, but a known provider shape must flag
  on sight regardless.
- Bundle-excluded files were initially reachable via import closure; now
  barred per decision 1 above.
- `check` initially flagged `__pycache__` byproducts as unrecorded extras,
  which made check fail on any fixture that had actually been run. Now
  ignored and listed.
- No tests were edited or weakened.

## Smoke + verification results (parent machine, this build)

Demo project (app.py + pkg/{__init__,core,helper,deep}.py + secretcfg.py
with a planted fake GitHub token shape + unrelated.py), real GhostSlice
export for the seed bundle:

- Seed = app.py, pkg/core.py, secretcfg.py (helper/deep simply unlisted):
  build exit 0, 5 files / 260 bytes copied. pkg/helper.py and pkg/deep.py
  arrived as import-closure with importers named (via pkg/core.py,
  via pkg/helper.py). unrelated.py absent. secretcfg.py excluded-flagged
  [github-token, sensitive-assignment]; the planted value appears nowhere
  in the output tree (grep clean).
- The built fixture RUNS: `python3 fixture/app.py` prints (43, '/').
- Source project sha256 set identical before and after the build.
- Check: OK on the fresh fixture (including after running it, pycache
  ignored), exit 1 with a named sha256 mismatch after tampering a file.
- `--max-bytes 200`: 3 files / 199 bytes kept (referenced first), app.py
  and pkg/helper.py left out with reason size-cap; cap stated in output.
- `--include-flagged`: secretcfg.py copied, flag stays on record with
  included_by_override.
- Output inside the project: refused, exit 2.
- Symlinks: a referenced link to /etc/hostname left out
  (symlink-escapes-root); a link to a file inside the project copied as
  content, not as a link.
- JS closure: main.js importing './util.js' and require('./extra') pulled
  both into the fixture.
- MCP: initialize and tools/list answer correctly; check_fixture callable.
- Fresh-venv `pip install .` verified: installed CLI reports 0.1.0 and
  builds a fixture.
- Agent B's suite against this core: **32 passed, 0 failed**
  (`python3 -m pytest tests -q`, final run).

## Known limits (also stated in every fixture manifest)

- Closure is static and parse-level. Dynamic imports, string-built module
  paths, reflection, and plugin loaders are not traced. Languages other
  than Python and JS/TS get no closure in v0.1 and are labelled as such.
- Secret shapes are a conservative net, not a proof: "not flagged" never
  means "secret-free". An unshaped secret in a copied file will travel.
- The fixture is not guaranteed to run: packages, data files, or services
  the bundle never referenced are recorded as external references at best.
- Python import resolution is heuristic at the edges (namespace packages,
  src-layout without an installed package, sys.path tricks): candidates
  are project-relative files only, and a resolution that does not land on
  a real file is recorded as an external reference, not guessed.
- Files are read into memory one at a time; the size cap bounds the total
  copied, and a single file larger than the cap is left out without being
  read, but a file just under a very large user-set cap is still one read.

## Gates held

Stdlib only (import audit: argparse, ast, hashlib, json, math, re, sys,
collections, dataclasses, datetime, pathlib; no network, subprocess, or
third-party tokens anywhere under src/). Local only, no GitHub push, no
PyPI/publish, no announcements, no spend. Source projects never modified.
