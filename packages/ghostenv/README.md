# GhostEnv
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostenv/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostenv/actions/workflows/ci.yml/actions)

**Are the names your code needs the names your .env actually has?**

Projects break in a boring, expensive way: code starts reading a
new environment variable, nobody adds it to `.env.example`, and
the next person (or the next agent run) finds out at runtime.
GhostEnv is the doctor for that. It compares three name sets:

1. names the code uses (`os.environ` / `os.getenv` in Python,
   `process.env` in JS/TS, `os.Getenv` in Go, `env::var` in Rust,
   shell `$NAME`, and parser-lite Ruby `ENV[...]` / `ENV.fetch`
   and Java/Kotlin `System.getenv` / Spring `@Value("${...}")`),
2. names defined in `.env`,
3. names documented in `.env.example`,

and reports the differences: used but not defined, used but not
documented, documented but no longer used, defined but never used,
duplicated, case-mismatched spellings of the same name, and
malformed lines.

**Names only, never values.** GhostEnv reads values only far
enough to know a line is shaped like `NAME=...`. No report, no
generated file, and no log line ever contains a value from a
`.env`. That rule is enforced by a dedicated leak test with a
planted fake canary value: if the canary ever appears in any
output, the suite fails.

It can also generate a clean `.env.example`: every used and
defined name, with empty placeholder values, ready to commit.

By Ghost Developer Studio. MIT core. Zero dependencies: Python
standard library only, local-first, no network, no telemetry.

Position in the Ghost stack: GhostSlice governs what an agent
reads, GhostExposure records what a sensitive bundle contains,
GhostEnv governs whether a project's environment contract is
documented and consistent. Agent Seatbelt still governs what an
agent does.

## Install

```bash
cd ghostenv
pip install .
ghostenv --help
```

Or run from a checkout without installing:

```bash
PYTHONPATH=src python3 -m ghostenv --help
```

Requires Python 3.10 or newer. The shipped CLI's `--help` is the
authority for exact subcommand spelling and flags
(`ghostenv --help`, `ghostenv check --help`, and so on).

## Which command do I want?

| Command | Question it answers | Writes anything? |
|---|---|---|
| `ghostenv scan <project>` | Which names does the code read? | No |
| `ghostenv check <project>` | Do code, `.env`, and the example file agree on names? | No |
| `ghostenv example <project>` | What would a clean, names-only `.env.example` look like? | Only the example file it names |

Start with `check` for a project you already have; use `scan`
when you only want the code side, and `example` when the check
says the example file is missing or stale.

## Quickstart

```bash
# Just the code side: names used, with file and line per read site
ghostenv scan ~/my-project

# Check a project: code usage vs .env vs .env.example
ghostenv check ~/my-project
echo $?   # 0 = no blocking findings, 1 = blocking findings
          # (the verdict line names exactly which), 2 = could
          # not scan

# The same check as machine-readable JSON (names only, as always)
ghostenv check ~/my-project --json

# Generate a clean .env.example (names + empty placeholders)
ghostenv example ~/my-project -o ~/my-project/.env.example.new
# Review it, then rename it over the old example. GhostEnv never
# modifies your real .env.
# Prefer to look before writing anything? Preview instead:
ghostenv example ~/my-project --stdout
```

A worked walkthrough lives in [`examples/`](examples/README.md).

## What it reports

| Finding | Meaning |
|---|---|
| used, missing from `.env` | Code reads a name nothing defines locally. It will fall back to a default or crash. |
| used, missing from `.env.example` | The contract is undocumented. The next checkout will not know to set it. |
| in `.env.example`, not used | Stale documentation, or a name used outside scanned code (say so in a comment). |
| in `.env`, not used | Possibly dead, possibly set for a tool the scanner does not read. Evidence, not proof. |
| duplicate name | The same name defined twice in one file. Which one wins depends on the loader. |
| case mismatch | The same name spelled with different case in different places (`Api_Url` in code, `API_URL` in `.env`). On case-sensitive systems those are different variables. |
| malformed line | A line that is neither blank, comment, nor `NAME=...`. Reported by file and line number only; the line's content is never shown, because it may be a bare value. |

Blocking findings fail the check (exit 1): a used name missing
from `.env` with no default at any read site, a missing example
file, a case mismatch, a duplicate, or a malformed line. The
verdict line names exactly which blocking findings fired. Soft
findings (every read site has a default), stale entries, and a
name missing from an example file that exists are reported but
do not block on their own.

## The names-only rule, stated plainly

- Reports contain variable names, file paths, and line numbers.
- Reports never contain values, prefixes of values, or hashes of
  values.
- A generated `.env.example` contains names with empty values or
  clearly labelled placeholders only.
- The test suite plants a unique fake canary value in a fixture
  `.env` and asserts it appears in no stdout, stderr, report, or
  generated file, ever.

## Optional config: `.ghostenv.json`

A project can carry an optional `.ghostenv.json` in its root.
Only two keys are honoured, and both contain names and patterns
only, never values:

```json
{
  "external": ["PLATFORM_PROVIDED_NAME"],
  "ignore": ["generated/*"]
}
```

- `external`: names a host, CI system, or deployment platform
  provides, so they will never appear in a local `.env`. They are
  excluded from the missing checks and listed as external, so the
  contract stays complete instead of crying wolf.
- `ignore`: extra glob patterns for paths the scanner should
  skip, matched against each file's project-relative path and
  file name.

The file is optional; a missing or unreadable one simply means
no externals and no extra ignores.

## Reading an exit code

- `0`: the run finished; for `check`, no blocking findings.
- `1`: `check` found blocking findings. The verdict line (and
  `blocking_reasons` in `--json`) names exactly which categories
  fired, so read that before hunting through the findings.
- `2`: GhostEnv could not do the run at all: the project path is
  not a directory, or `example` refused to overwrite an existing
  example file. For the refusal, re-run with `-o <path>` to write
  elsewhere, `--stdout` to preview, or `--force` to overwrite on
  purpose.

## Limits

- Static scanning finds name usage in the patterns it knows.
  Dynamic lookups (`os.environ[some_variable]`, computed names,
  f-string names, reflection) cannot be resolved: the scan
  counts them as dynamic read sites by file and line, and the
  names they read stay invisible to the report.
- Reads mentioned in full-line comments are not counted, and
  reads inside string literals can be counted. Parser-lite,
  labelled as such.
- Ruby and Java/Kotlin scanning is parser-lite throughout:
  findings carry a `parser-lite` confidence marker. Defaults are
  detected structurally only (a fetch/getOrDefault argument, a
  `||` / `?:` fallback, a fetch block, or the colon in a Spring
  `${NAME:default}` placeholder); default text is never read
  into any output, same as every other language.
- A clean check is evidence that the three name sets agree. It
  is not proof an application will run: values can still be
  wrong, empty, or point at the wrong place, and GhostEnv
  deliberately never inspects them.
- Frameworks and deployment platforms inject names code never
  mentions. Treat an unused or undocumented finding as a prompt
  to document, not an automatic fault.

## Out of scope for v0.1

- Reading, storing, syncing, or validating secret values.
- Writing to a real `.env` (generation targets an example file).
- Cloud secret managers, accounts, telemetry, paid layer.

## Tests

```bash
python3 -m pytest tests -q
# or
python3 -m unittest discover -s tests
```

The suite is black-box: fixture tests always run; CLI tests drive
the shipped CLI (discovered from `--help`) and skip cleanly if no
CLI is present yet. It includes planted-missing-name fixtures, a
malformed `.env` fixture, and the canary leak test described
above.

## Layout

```
src/ghostenv/   the tool (Agent A)
tests/          black-box suite + fixtures (names + fake values only)
examples/       mini project walkthrough, fake placeholders only
PLAN.md         the v0.1 plan
```

---
<!-- ghost-studio-footer -->
## More from Ghost Developer Studio

Ghost Developer Studio builds developer tools, AI-agent safety software, and practical apps, and sells by showing working software, not slide decks.

- [Roadmap board](https://github.com/littlestjames82-sys/ghost-roadmaps): where every studio product stands
- [Agent Seatbelt](https://github.com/littlestjames82-sys/agent-seatbelt): deterministic guardrails for AI coding agents
- [Ghost Hands](https://github.com/littlestjames82-sys/ghost-hands): governed, recorded, replayable agent hands
- [GhostSlice](https://github.com/littlestjames82-sys/ghostslice): agent context and prompt optimizer
- [GhostIDE](https://github.com/littlestjames82-sys/ghostide-android): fully offline AI code editor for Android
- [All studio projects](https://github.com/littlestjames82-sys?tab=repositories)
