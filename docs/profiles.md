# Profiles and CI

Part of the [GhostSlice README](../README.md). The project profile, the init wizard, and the CI gates.

## Profiles: `.ghostslice.json` (v0.2)

Drop this in a project root and every command picks it up automatically:

```json
{
  "ignore": ["vendor/**", "*.snap"],
  "modes": {"src/**": "signatures", "docs/**": "full"},
  "model": "claude-sonnet",
  "budget_tokens": 50000,
  "entry_points": ["src/main.py"],
  "preset": "claude-code"
}
```

Export presets: `claude-code` (the `.claude_context` bundle), `aider`
(adds `aider-files.txt`, a plain list of the sliced files to pass to
Aider with `--read`), `generic` (adds a lowercase `prompt.md`),
`cursor` (v0.5: adds `prompt.md` plus a `README.txt` explaining how to
paste/attach the bundle in Cursor; meant to live as a `.cursor-context`
directory), `copilot` (v0.5: adds a `prompt.md` shaped for GitHub
Copilot Chat, one `## File:` section per file with fenced code blocks),
`anthropic-xml` (v0.16: adds `context.xml`, an Anthropic-style XML
document of the slices), and `json` (v0.16: adds `context.json`, a
machine-consumable JSON object of the slices). See
[XML and JSON bundles](commands.md#xml-and-json-bundles-v016)
for both schemas.
Nested `.gitignore` files in subdirectories are honoured, scoped to
their subtree. An optional `"lint"` section tunes the context linter
per rule (see [Context lint](commands.md#context-lint-v011)),
`"auto_shrink": true` makes
exports exclude detected generated/vendored/minified files (see
[Detection + auto-shrink](commands.md#detection--auto-shrink-v012)), and `"redact": true` makes exports
replace flagged secret values in place (see [Redact in place](commands.md#redact-in-place-v017)).
Two floor sections (v1.0.2) tune duplicate detection:
`"duplicates": {"near_min_chars": N}` moves the near-duplicate
size floor (default 200 normalized characters; see
[Duplicates](commands.md#duplicates-v04))
and `"ci": {"duplicates_floor_tokens": N}` moves the CI
duplicates gate floor (default 500 recoverable estimated tokens;
see [the CI pack](#ci-pack-one-gate-command-v024) below). Both take positive whole numbers, unknown
keys are a loud error at load time exactly like the `"lint"`
section, and unset means the documented defaults. The floors are
profile-only settings: no CLI flag overrides them for one run.

## Init: generate a tuned profile (v0.15)

```bash
ghostslice init ~/my-project                 # interactive on a TTY, --yes otherwise
ghostslice init ~/my-project --dry-run       # print the profile + evidence, write nothing
ghostslice init ~/my-project --budget 80000 --model claude-sonnet
```

`init` analyses the project with the tool's own engines (scan, the
import graph, detect.py flags, the context linter) and writes a
`.ghostslice.json` where every section carries a printed
justification:

- **entry_points**: the top candidates (cap 5), ranked by signal —
  a package.json `"bin"` entry or a pyproject `[project.scripts]`
  entry (+60), package.json `"main"` (+50), the entry-name heuristic
  shared with the prune engine (+40), a Python
  `if __name__ == "__main__"` guard (+35), a shebang (+25), and
  "nothing imports it" (+10, tie-breaker only). Test files and
  vendored/generated files are never nominated: a false entry point
  is worse than a missing one, because exports protect entry points
  from auto-shrink and fit downgrades.
- **ignore**: directory trees whose files are all flagged vendored
  by path. **modes**: directories whose files are all flagged
  generated get `"exclude"`; config-heavy directories (≥70%
  config/data files, ≥3 files, ≥500 estimated tokens) get
  `"structure"`. Docs and tests are deliberately not pinned — the
  built-in defaults already handle them.
- **budget_tokens**: your `--budget`, or the current default-sliced
  total × 1.25 rounded up to two significant figures, so
  `check-budget` catches growth. Projects slicing under 5,000 tokens
  get no budget (it would be noise) — the omission is printed, with
  the number. **model** is written only from `--model`; init never
  invents one. No `"lint"` section is written in this version: lint
  stays at its defaults rather than freezing today's findings into
  config.

Safety: an existing `.ghostslice.json` is refused (exit 2, with a
summary of what's in it) unless `--force` is given; `--dry-run`
writes nothing at all; the written file is loaded back through the
real profile loader before init reports success. On a TTY you are
asked per section (entry points, file rules, budget) with the
analysis as the default; piped stdin behaves as `--yes` and says so.
The output ends with the top 3 "biggest wins" from the analysis and
the linter — guidance only; init changes nothing but the profile.

## Budget gate for CI (v0.2)

```bash
ghostslice check-budget ~/my-project --max-tokens 50000   # or profile budget_tokens
echo $?   # 1 when the selected (sliced) context exceeds the budget
```

## CI pack: one gate command (v0.24)

`ghostslice ci` runs the whole context-health gate in one
read-only pass and reports five named checks, each with a
one-line evidence string:

```bash
ghostslice ci ~/my-project                      # budget from the profile
ghostslice ci ~/my-project --budget 50000       # or from the flag
ghostslice ci ~/my-project --json               # one machine payload
ghostslice ci ~/my-project --pr-comment         # Markdown for a PR comment
ghostslice ci ~/my-project --out report.html    # plus the HTML report
```

The checks: **budget** (sliced context vs the configured budget;
skipped, not failed, when no budget is configured anywhere),
**lint** (the context-lint rules; errors fail, warnings fail only
with `--strict`), **secrets** (guard findings FAIL by default,
because the gate's job is keeping secrets out of agent context;
`--allow-secrets` downgrades them to a warning for the whole run,
including lint's L005 rule), **fit** (whether the auto-fit ladder
can reach the budget from the default selection), and
**duplicates** (exact-duplicate groups holding 500+ recoverable
estimated tokens warn; the floor is a profile setting, v1.0.2:
`"ci": {"duplicates_floor_tokens": N}` in `.ghostslice.json`).
Exit codes: 0 when no check failed
(warnings and skips never fail a run), 1 when any check failed,
2 for usage/config errors. The run writes nothing (no bundle, no
ledger record, no cache) unless `--out` names a report file; a
check that errors internally fails that check alone, never the
run. Token counts are estimates.

A copy-paste GitHub Actions workflow lives in
`examples/github-action/` (installs GhostSlice from its GitHub
repo, since it is not on PyPI, uploads the JSON/report artifacts,
and can post the `--pr-comment` summary). This repo dogfoods the
command in `.github/workflows/ghostslice-ci.yml`. One local-run
note: a report written into the project tree is a file like any
other, so later runs scan it; gitignore the report names if you
use `--out` locally.
