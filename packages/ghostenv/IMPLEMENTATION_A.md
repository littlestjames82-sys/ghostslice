# GhostEnv v0.1 - Implementation A (core owner)

Built Oct 14, 2026, Wave 3, at Ryan's "All of them" (build all Wave 3 tools at once, 2 agents per tool, same pattern as the 13 companions). Agent A owned: PLAN.md, pyproject.toml, src/**, this file. Agent B owns tests / README / examples (REPORT_B.md). Gates held: stdlib only, local only, NO push, NO publish, NO announcements, NO spend, NO network.

## What was written
- `PLAN.md` - full plan in Slice format (template: GhostVerify PLAN.md): why this name, the problem (three drifting name lists: code / .env / .env.example), position in the stack (Env contract vs Slice context vs Exposure surface evidence), the names-only rule as a non-negotiable section, MVP, out of scope, build estimate (~1 week), pricing draft (NOT decided), verification bar, risks, next gate. Inspiration stated in the plan: the manual GhostBus flagged-key cleanup, Oct 13-14, 2026.
- `pyproject.toml` - ghostenv 0.1.0, MIT, zero dependencies, `ghostenv = ghostenv.cli:main`, src layout matching the companion tools.
- `src/ghostenv/__init__.py` - version + NAMES_ONLY_STATEMENT, rule stated in the docstring.
- `src/ghostenv/envparse.py` - names-only .env parsing: anchored regex captures only the name before the first `=` (supports `export KEY`, bare `KEY`, comments); the right-hand side is never captured or stored. Duplicates reported by name + line numbers. Also: example-file discovery (`.env.example` / `.env.sample` / `.env.template`) and `.ghostenv.json` config (`external` names, `ignore` globs; invalid names dropped).
- `src/ghostenv/scanner.py` - static code scan. Patterns: Python (`os.environ[...]`/`.get`/`.setdefault`/`.pop`, `os.getenv`, bare `environ[...]`/`getenv(...)`, membership `"NAME" in os.environ`), JS/TS (`process.env.NAME`, `process.env["NAME"]`, destructuring from `process.env`, `||` fallback), Go (`os.Getenv`, `os.LookupEnv`), Rust (`env!`, `option_env!`, `env::var`), shell `$NAME`/`${NAME}` (uppercase only, confidence `parser-lite`). Dynamic reads (non-literal name argument) are counted as sites by file + line, never guessed. Skips .git, node_modules, venvs, dist/build/vendor, env files themselves, binaries by size/extension.
- `src/ghostenv/doctor.py` - the three-set comparison and classifications: missing-in-env hard (a non-shell read site with no default) vs soft (every site has a default, or shell-only), missing-in-example, stale-in-env, stale-in-example, case-mismatch (names differing only by case or `-` vs `_`, across sets), duplicate, external. Missing example file with names to document also counts hard. Exit code in the report: 0 complete, 1 hard findings / case mismatch / duplicates. Default-ness is computed per source location (a location matched by both a plain and a fallback pattern counts once, with the fallback).
- `src/ghostenv/examplegen.py` - generation from a name set ONLY: the function receives names and nothing else, so no code path can carry a value into the output. Output: header stating names-only, names grouped by prefix before the first `_`, every line `NAME=` with an empty right-hand side.
- `src/ghostenv/reports.py` - text rendering for `check` and `scan`.
- `src/ghostenv/cli.py` - `scan` / `check` / `example`. Exit codes 0 / 1 / 2 (could not scan or refused). `scan` and `check` write nothing. `example` refuses to overwrite an existing example file without `--force`; `-o <path>` writes elsewhere; `--stdout` prints. `--json` on scan (names + usages + dynamic sites) and check (full report).

## The names-only invariant, in code
- envparse: the assignment regex is anchored and has exactly one capture group, the name. Values are not assigned, hashed, compared, or logged anywhere in the package.
- scanner: patterns capture only the name group; a default's *presence* is detected structurally (a `,` group, a `||` group, `=` in a destructured entry) and the literal text is never read from the match.
- doctor / reports / CLI: data structures carry names, relative paths, line numbers, pattern kinds, and booleans only.
- examplegen: takes a set of names, by signature. It cannot leak a value it never receives.

## Smoke verification (Agent A's own runs, fixtures in /tmp, planted fake values)
- Fixture project (Python + JS + Go): scan found all 10 used names across the three languages, plus 1 dynamic read site. Check classified correctly: hard (API_URL, GO_ONLY_KEY, GO_LOOKUP_KEY, STRIPE_KEY), soft (DATABASE_URL, NODE_ENV, and CACHE_TTL after the fix below), missing-in-example (9), stale-in-env (UNUSED_LOCAL), stale-in-example (OLD_REMOVED_KEY). Exit 1.
- Leak test: fixture `.env`, code defaults, and example comments were planted with distinctive fake value strings; the JSON check report was grepped for all of them - NO LEAK. (Agent B's suite should turn this into a permanent adversarial test on every output surface, per the PLAN verification bar.)
- Case fixture: code reads `Api_Url`, `.env`/example define `API_URL`, defined twice - check reported the case-mismatch pair and the duplicate with both line numbers. Exit 1.
- Clean fixtures: soft-only project (default at the only read site, documented) exits 0; fully aligned project exits 0.
- Example flow: `example --stdout` prints a grouped names-only file; plain `example` after the file exists refuses with exit 2 and a `--force` / `-o` hint; `-o` writes.
- Real-repo run: `scan` on ~/workspace/ghostbus finds GHOSTBUS_ADMIN_KEY (deploy/netlify/functions/ghostbus.mjs:21, +2 more, matching the Oct 13-14 cleanup finding that the function and server read the admin key from the environment), GHOSTBUS_PORT, GHOSTBUS_DATA_DIR, and 4 dynamic read sites. Shell noise is visible as expected (AGE, NOW, STATE from example .sh scripts): shell is parser-lite by design and can only produce soft findings.
- `python3 -m compileall src/ghostenv` passes. Package runs via `PYTHONPATH=src python3 -m ghostenv ...` (the sandbox Python is externally managed, so `pip install -e .` is blocked by PEP 668 here; the pyproject is standard setuptools and matches the other companions).

## Fixes made during smoke testing
1. `process.env["X"] || fallback` was first reported hard: the plain subscript and fallback patterns produced duplicate rows and dedupe dropped the fallback marker. Dedupe now merges `has_default` (OR) for the same (name, file, line, kind), and doctor computes default-ness per source location.

## Known limits (stated in PLAN, repeated here)
- Regex/parser-lite scanning, including for Python: multiline calls with the name on a later line, and aliased imports beyond the covered bare forms, can be missed. Static scan undercounts by design; copy says "no missing names found by static scan", never "this project will run".
- Shell findings are noisy (any uppercase `$NAME`); they never produce a hard finding alone.
- `stale-in-env` is a prompt to look, not a deletion verdict: hosts, tools, and one-off scripts read names code never touches (hence `.ghostenv.json` `external`).
- No value is ever inspected, so a present-but-wrong value is undetectable by design.

## For Agent B
- Tests should cover: each classification in isolation, the per-location default rule (JS `||` subscript case above), duplicates, case-mismatch, external names, missing .env / missing example, example overwrite refusal + `--force` + `-o`, the exit codes, and the release-blocker names-only test (planted values in .env lines, code defaults, and example comments must appear in NO output: scan text, scan JSON, check text, check JSON, generated example).
- A demo fixture project (drifted on purpose, fake values only) under examples/ would match the family pattern.
- Nothing here is pushed, published, or announced. Releases remain Ryan-gated.
