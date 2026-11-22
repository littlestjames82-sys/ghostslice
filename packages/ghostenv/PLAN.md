# GhostEnv - Local .env Doctor for Agent-Run Projects
Working name, prepared Oct 14, 2026. Wave 3 paired tool for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostEnv: plain job, plain name. It doctors a project's environment variable contract: what the code uses, what `.env` defines, and what `.env.example` documents.
- Checked against the family: sits next to GhostExposure (evidence about a sensitive surface) and GhostSlice's secrets guard (findings in code). Neither of those answers "which variables does this project actually need, and are they all named in the right places?"
- Alternatives held in reserve: GhostDotEnv (clear but long, and ties the name to one file convention when JS, Go, and Rust projects all read the same process environment), GhostVars (too vague).

## The problem
Every project Ryan runs agents on has three separate lists of environment variable names, and they drift apart silently:

- The names the code actually reads (`os.environ`, `os.getenv`, `process.env`, `os.Getenv`, `env::var`, and friends).
- The names defined in the local `.env` file.
- The names documented in `.env.example` (or `.env.sample` / `.env.template`).

When they drift, the failures are boring and expensive: an agent run dies twenty minutes in on a variable nobody documented, a renamed variable leaves a stale entry that looks load-bearing, a new variable lands in code and in a local `.env` but never in the example file, so the next clone, worktree, or teammate cannot run the project at all.

Worse, the usual fix is manual and unsafe. On Oct 13-14, 2026 the GhostBus flagged keys had to be resolved by hand: grep the repo, prove each literal was test-only, check what the real function and server read from the environment, and replace literals with labelled placeholders. That worked, but it was one repo, done carefully, by hand. There is no repeatable, names-only check that says "code uses these names, `.env` defines these names, the example documents these names, here is the exact mismatch", without ever printing a value.

Today there is no such doctor. Developers either paste `.env` contents into a chat (leaking values), copy a local `.env` into `.env.example` (leaking values into git), or guess.

## Position in the Ghost stack
- GhostSlice governs what an agent READS (scanner, AST slicer, token estimator, `.claude_context` bundle).
- GhostExposure governs evidence about a sensitive SURFACE (what is in and out of an audit bundle, verified against its manifest).
- GhostEnv governs a project's environment CONTRACT: the set of variable names the code needs, checked against the names defined locally and the names documented for the next person.
- Agent Seatbelt governs what an agent DOES. GhostEnv runs no agent and takes no action; it reports and generates a names-only example file.

Story: Env (is the contract complete?) -> Slice (prepare context) -> Verify (was it enough?) -> agent runs under Seatbelt.
No overlap: Slice's secrets guard and Exposure flag secret-shaped literals by path + line + type. GhostEnv never looks at values at all: it works on names only, by construction (see the names-only rule below).

## The names-only rule (non-negotiable, v0.1 and after)
- GhostEnv parses `.env`-style files by splitting each line at the first `=` and discarding the right-hand side immediately. Values are never stored in any data structure, report, ledger, or test fixture.
- Code scanning records a variable name, its file, its line, the access pattern, and a boolean "a default / fallback was present". A default literal in code is never copied into output.
- Every output surface (terminal, `--json`, generated `.env.example`, reports) contains names, file paths, line numbers, and present/absent booleans only.
- A generated `.env.example` contains `NAME=` lines with empty right-hand sides, grouped and commented from names alone. It is never produced by copying or transforming a real `.env` file's lines.
- If a future feature would need a value, it is out of scope by definition. GhostEnv answers "is a name present?" and nothing else.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Scanner discipline: same ignore rules as Slice (`.gitignore` respect in spirit, hard skips for `.git`, `node_modules`, virtualenvs, build output), same "parser-lite, labelled" honesty for non-Python languages.
- Secrets guard behaviour: matches Slice v0.4's rule that findings are path + line + type only. GhostEnv goes one step further: it does not even classify values, it never retains them.
- Profile: respects `.ghostslice.json` if present for ignore paths, and reads its own optional `.ghostenv.json` for extra ignore globs and known external names (variables provided by a host, CI, or platform that will never appear in a local `.env`).
- GhostWorktree (Wave 3): a fresh worktree is exactly where a missing example entry bites. Env's `check` is the natural pre-flight for Worktree's per-agent `.env` copy step, and Worktree should copy names-verified files, never invent them.
- GhostLedger / GhostProxy (Wave 3 / Wave 1): those tools must never log keys. Env's names-only report is the safe vocabulary for referring to configuration in their logs.

Integration contract:
- Input: a project path. Optional: explicit `--env-file` and `--example-file` paths (defaults: `.env` and the first of `.env.example`, `.env.sample`, `.env.template` in the project root).
- Output: a names-only report (text or JSON) and, for `example`, a generated example file. Nothing is written by `scan` or `check`. `example` writes only the file the user names (or, with `--force`, the project's example file).
- No network, no shelling out, no reading outside the project root except files the user explicitly passes.

## MVP (v0.1) - local CLI first, stdlib only
Rationale: same as Slice v0.1. A CLI proves the doctor on real repos in days, and its JSON report is what CI, GhostWorktree, and later dashboard panels consume.

1. Code usage scan: `ghostenv scan <project> [--json]`
   - Walks the project (skipping `.git`, `node_modules`, `__pycache__`, `.venv`/`venv`, `dist`, `build`, `vendor`, and binary files) and finds environment reads:
     - Python: `os.environ["NAME"]`, `os.environ.get("NAME", ...)`, `os.getenv("NAME", ...)`, bare `environ[...]` / `getenv(...)` after a matching import, `os.environ.setdefault`, and `NAME in os.environ` membership checks.
     - JavaScript / TypeScript: `process.env.NAME`, `process.env["NAME"]`, and destructuring `const { NAME, OTHER } = process.env`.
     - Go: `os.Getenv("NAME")`, `os.LookupEnv("NAME")`.
     - Rust: `env!("NAME")`, `option_env!("NAME")`, `std::env::var("NAME")`, `env::var("NAME")`.
     - Shell (`.sh`, `.bash`): `$NAME` and `${NAME}` / `${NAME:-default}` for uppercase names only, labelled parser-lite (shell variables are not all environment variables; findings carry a lower-confidence marker).
     - Dynamic reads (a variable holding the name, template strings, `getattr`-style indirection) cannot be resolved statically: they are counted and reported as "dynamic read sites" by file + line, never guessed at.
   - Each finding: name, relative file, line, pattern kind, `has_default` boolean. No argument text beyond the name is ever emitted.
   - Names that are not plausible environment names (not matching `[A-Za-z_][A-Za-z0-9_]*`) are dropped.

2. `.env` and example parsing (names only)
   - Parses `KEY=...`, `export KEY=...`, bare `KEY` lines, comments, and blank lines. Duplicate names are reported with both line numbers. Quoting, escapes, and multiline values are deliberately not interpreted: the parser only needs the name before the first `=`, and a value's content can never affect that.
   - A missing `.env` or a missing example file is a finding, not a crash: a project with code usage and no example file fails `check` on exactly that point.

3. Doctor check: `ghostenv check <project> [--json]`
   - Compares the three name sets and classifies every name:
     - `missing-in-env`: used in code, not defined in `.env`. Hard when at least one read site has no default; soft (labelled) when every read site supplies a default or fallback.
     - `missing-in-example`: used in code (or defined in `.env`), not documented in the example file.
     - `stale-in-env`: defined in `.env`, never used in code and not documented. Labelled "possibly provided for a tool, script, or host", never asserted dead.
     - `stale-in-example`: documented, never used in code and not defined locally.
     - `case-mismatch`: a name in one set differs from a name in another only by case or by `-` vs `_`. Reported as a likely typo pair, with both spellings.
     - `duplicate`: same name defined twice in one file, with line numbers.
     - `external`: names listed under `external` in `.ghostenv.json` (host/CI/platform provided). Excluded from missing checks, still listed so the contract is complete.
   - Exit codes: 0 = contract complete (no hard findings), 1 = hard findings, 2 = could not scan (bad path, unreadable required file explicitly passed). Soft findings alone do not fail the check, and the report says so.

4. Example generation: `ghostenv example <project> [-o <path>] [--stdout] [--force]`
   - Generates a clean example from names only: the union of names used in code, defined in `.env`, and already documented, sorted, grouped by the prefix before the first `_` (for example `GHOSTBUS_`, `TURSO_`), each line `NAME=` with an empty right-hand side, under a header that states the file was generated by GhostEnv and contains no values.
   - Names already documented keep no old comments: comments can contain values or hostnames, so v0.1 regenerates comments from names alone (group headers only). This is stated in the header.
   - Refuses to overwrite an existing file without `--force`. `--stdout` prints instead of writing. Generation never opens the local `.env` for anything but its names, through the same discarding parser as `check`.

5. Report shape (Bench / Worktree ready)
   - JSON report: tool version, project path, scanned file count, dynamic read site count, the three name sets (sorted), findings grouped by classification with file + line evidence, and counts. No values, no default literals, no file contents.
   - Text report: the same, grouped and readable, ending with a one-line verdict.

## Out of scope for v0.1
- Reading, printing, comparing, hashing, or storing any secret value, for any reason. Also out: detecting whether a value is "weak", "real", or a placeholder. That requires values.
- Editing a real `.env` file, filling in values, fetching values from a vault, a host, or CI, or syncing values between machines.
- Running the project, importing its code, or executing shell files to see what they read. Static scan only.
- Languages and frameworks beyond the patterns above (no Django settings introspection, no Spring `@Value`, no Ruby `ENV[...]` in v0.1; Ruby and Java are candidates for v0.2, labelled parser-lite if added).
- Cloud, accounts, telemetry, paid layer, network of any kind.

## Build estimate
- Names-only `.env` parser + code scanner (Python and JS/TS first, Go/Rust/shell parser-lite): 2-3 days
- Set comparison, classifications, case-mismatch pairing, report (text + JSON): 1-2 days
- Example generation (grouping, overwrite guard): 1 day
- Tests (names-only adversarial fixtures: values planted in `.env`, defaults, and comments must appear nowhere in any output), README, demo on GhostBus: 1-2 days
Total: roughly 1 week to a verified v0.1 if built straight through. The scanner is the part most likely to slip, and shell findings are the first thing to cut if it does, with the cut stated up front.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team contract packs / CI gate history. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Names-only test (release blocker): fixtures plant distinctive fake values in `.env` lines, in code default arguments, and in example-file comments. Every GhostEnv output surface (scan, check in text and JSON, example generation) is asserted to contain none of those strings, byte for byte.
- GhostBus test: run against the GhostBus tree after its Oct 13-14 key cleanup. `check` must name the environment variables the Netlify function and hosted server read (admin key read from the environment, per that cleanup), with no value ever shown.
- Drift test: a fixture project with one name in each classification (missing hard, missing soft, stale, case-mismatch, duplicate, external) must produce exactly those classifications.
- Example test: a generated example from a drifted fixture, placed next to the code, makes `check` pass on the `missing-in-example` classification and contains only `NAME=` lines.
- Every report reproducible from the JSON output alone: name sets + findings + counts, no hidden state.

## Risks / honest notes
- Static scanning undercounts by design: dynamic name construction, framework magic, and variables read by tools (not code) will be missed or flagged stale. Copy must say "no missing names found by static scan", not "this project will run".
- Shell findings are noisy: not every `$NAME` is an environment variable. Shell results carry a confidence marker and never produce a hard finding on their own in v0.1.
- `stale-in-env` is a prompt to look, not a verdict: hosts, deploy platforms, and one-off scripts read names code never touches. That is why `.ghostenv.json` `external` exists.
- The names-only rule limits diagnosis: GhostEnv can say a name is absent, never that a present value is wrong, expired, or pointed at the wrong environment. That is a deliberate trade, and the report states it.

## Next gate
Ryan's go on: (1) GhostEnv as working name, (2) CLI-first with `scan` / `check` / `example`, (3) the names-only rule as a hard, test-enforced invariant, (4) build order within Wave 3.
