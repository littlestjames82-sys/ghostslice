# GhostRecipes
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostrecipes/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostrecipes/actions/workflows/ci.yml/actions)

Versioned workflow recipes as data. Nothing more, and that is the point.

A recipe is a small JSON file that names a repeatable workflow: goal,
inputs, ordered steps, gates, and outputs. GhostRecipes can create a
recipe, list recipes, show one, validate one, export one, and render one
as a checklist you can work through.

> **Hard rule: GhostRecipes never runs a recipe.**
> Steps that name a command are text in a file. They are never executed
> by `create`, `list`, `show`, `validate`, `export`, `import`, or
> `render`. A human (or an agent the human directs) reads the checklist
> and decides what to do. This will not change silently: execution, if
> it ever exists, is a separate gate in a separate tool.

By Ghost Developer Studio. Companion to GhostSlice in the suite sense:
Slice shares context, GhostPacks shares profiles, Recipes shares
*process*.

## Quickstart (30 seconds)

You need Python 3.10 or newer. From the GhostRecipes folder, try the
bundled example with no setup and no install:

```bash
# Validate a starter recipe (exit 0 means valid)
PYTHONPATH=src python3 -m ghostrecipes validate examples/slice-marathon-loop.recipe.json

# Render it as a checklist you can follow by hand
PYTHONPATH=src python3 -m ghostrecipes render examples/audit-improve-verify.recipe.json --var target=myfile.py
```

That is the whole idea: validate the data, render a checklist, work
the checklist yourself. See `examples/WALKTHROUGH.md` for a longer
worked run.

## How to run it

Two equivalent entry points:

| Form | When to use it |
|---|---|
| `ghostrecipes ...` | After installing the package (`pip install .` from this folder). |
| `PYTHONPATH=src python3 -m ghostrecipes ...` | Straight from a source checkout, no install. Used in all examples below. |

Run `ghostrecipes --help` for the command list, or
`ghostrecipes <command> --help` for one command's flags.

## Commands at a glance

| Command | What it does |
|---|---|
| `create` | Scaffold a new, valid, versioned (0.1.0) recipe file. |
| `list` | List every recipe found in the library folders. |
| `show` | Print one recipe in full: steps, gates, inputs, file hash. |
| `validate` | Check a recipe file, folder, or id. Exit 0 means valid. |
| `export` | Copy a recipe into a data-only pack (recipe + `manifest.json`). |
| `import` | Verify a pack, then copy its recipes into a library folder. |
| `render` | Print a recipe as a Markdown checklist, filling `{{inputs}}`. |

```bash
# Create a new recipe skeleton
PYTHONPATH=src python3 -m ghostrecipes create --id my-new-loop --name "My New Loop" -o my-new-loop.recipe.json

# List recipes in a library folder
PYTHONPATH=src python3 -m ghostrecipes list --library examples/

# Show one recipe in full (by file path or by id)
PYTHONPATH=src python3 -m ghostrecipes show examples/slice-marathon-loop.recipe.json

# Validate one recipe, or a whole folder
PYTHONPATH=src python3 -m ghostrecipes validate examples/slice-marathon-loop.recipe.json

# Export a recipe as a data-only pack (recipe file plus manifest.json)
PYTHONPATH=src python3 -m ghostrecipes export examples/slice-marathon-loop.recipe.json -o out/slice-marathon-loop

# Import an exported pack back into a library folder
PYTHONPATH=src python3 -m ghostrecipes import out/slice-marathon-loop --library my-library/

# Render a recipe as a checklist (inputs can be filled with --var)
PYTHONPATH=src python3 -m ghostrecipes render examples/audit-improve-verify.recipe.json --var target=myfile.py
```

## Your first recipe in 2 minutes

```bash
# 1. Scaffold it
PYTHONPATH=src python3 -m ghostrecipes create --id weekly-review --name "Weekly Review" \
  --steps "Collect the week; Pick one fix; Verify the fix" -o weekly-review.recipe.json

# 2. Edit weekly-review.recipe.json: add detail and a gate to a step if you like

# 3. Validate it, then render the checklist
PYTHONPATH=src python3 -m ghostrecipes validate weekly-review.recipe.json
PYTHONPATH=src python3 -m ghostrecipes render weekly-review.recipe.json
```

## Library discovery

Commands that take an id (`show`, `validate`, `export`, `render`)
and `list` search these folders, in this order:

1. `--library DIR`, when given
2. `$GHOSTRECIPES_LIBRARY`, when set
3. `~/.ghostrecipes`
4. `./recipes` in the current folder
5. the bundled `recipes/` folder in the checkout

`--library` adds a folder to the front of that list. It does not
replace the rest, so a recipe in `~/.ghostrecipes` can still be
found while listing another folder. The same folder reached by two
different spellings (relative and absolute, for example) is scanned
once, and each recipe is listed once. `import` is the exception: it
writes to one target only, `--library` or `~/.ghostrecipes`.

## Exit codes and warnings

- `0` means success. `1` means validation failed, or a show, render,
  or export was refused because the recipe is invalid.
  `2` means a usage or config error (missing file, bad pack,
  unsafe pack entry, name collision without `--force`).
- Placeholder problems are warnings, not errors, so a draft still
  validates: a `{{name}}` used but never declared as an input, an
  input declared but never used, and a malformed placeholder such
  as `{{1bad}}` are each named in a warning. Render lists anything
  it could not fill in an Unresolved placeholders section.

## Packs

An export pack is a folder with the recipe file plus a
`manifest.json` holding a sha256 for each file. Import verifies the
manifest, every hash, and every recipe before it writes anything,
and it rejects path traversal entries, duplicate entries,
symlinks, and any file in the pack folder that fails the data-only
rules: wrong suffix, executable permission bit, or a shebang line,
whether the file is listed in the manifest or not.

Rendered output looks like this:

```markdown
# Slice Marathon Loop

Recipe: slice-marathon-loop v1.0.0 | file sha256: ...

- [ ] **1. Define one goal** (manual, id: define-goal)
- [ ] **2. Slice the context** (run, id: slice-context)
- [ ] **3. Build the goal** (run, id: build)
```

## Recipe format

A recipe is one JSON file, named `<id>.recipe.json`:

```json
{
  "id": "slice-marathon-loop",
  "name": "Slice Marathon Loop",
  "version": "1.0.0",
  "description": "What this workflow is for, on {{project}}.",
  "tags": ["build", "audit"],
  "author": "Ghost Developer Studio",
  "date": "2026-10-14",
  "inputs":  [{"name": "project", "description": "...", "required": true}],
  "steps":   [{"id": "define-goal", "title": "Define one goal",
               "kind": "manual", "detail": "...",
               "gate": "What must hold before continuing.",
               "command_hint": "a command, as text, run manually"}],
  "outputs": [{"name": "checked-result", "description": "...",
               "required": true, "from_step": "define-goal"}],
  "notes": "Anything the follower should know."
}
```

- `id` is a lowercase slug, `version` is semver (MAJOR.MINOR.PATCH).
  Together they name an exact recipe. Change the content, bump the
  version. A Markdown recipe form (`.recipe.md` with one fenced json
  block) is also accepted.
- Step `kind` is one of `manual`, `check`, `run`, `review`, `approve`,
  or `note`. `run` means the *follower* runs it. It is a label, never
  an instruction to this tool. A `command_hint` is printed text in the
  rendered checklist, labelled run manually.
- Step ids are unique inside a recipe. Step order is run order.
- `outputs` is optional. Each output declares what a follower should
  end up holding: a unique slug `name`, an optional `description`,
  an optional `required` flag, and an optional `from_step` naming
  the step that produces it (validated against the step ids).
  Render prints the outputs as a table after the steps, and `show`
  lists them. Declaring an output never creates it: it is an
  expectation to check against, not a file this tool writes.
- Unknown keys are rejected by name, at every level. That is what
  keeps execution hooks (an auto-run field, a script path, an on-load
  hook) out of the format entirely.
- Text can use `{{input_name}}` placeholders for declared inputs.
  Render fills them from input defaults or `--var name=value`, and
  lists any it could not fill instead of guessing.

## Starter recipes in examples/

- `slice-marathon-loop.recipe.json` - build one goal, audit, improve twice,
  verify, then move on. The GhostSlice marathon loop.
- `audit-improve-verify.recipe.json` - the short version: audit, two separate
  improvements, verify with evidence.
- `creator-pitch-draft-first.recipe.json` - creator outreach the studio way:
  verify facts, draft first, send approved text only, no em dashes in
  copy that will be sent or posted.

See `examples/WALKTHROUGH.md` for a worked run.

## Troubleshooting

- `recipe not found: '...'` - the id or path was not in any library
  folder. Pass the file path directly, or add its folder with
  `--library DIR`. See Library discovery above.
- `already exists; use --force` - `create`, `export`, and `import`
  refuse to overwrite by design. Re-run with `--force` only if
  replacing the existing file or folder is really what you want.
- A recipe validates but render lists Unresolved placeholders -
  a `{{name}}` had no default and no `--var name=value`. Supply the
  value, or add a `default` to that input in the recipe.
- `list --json` output will not parse - make sure you are parsing
  stdout only; in JSON mode the library header is printed to stderr.

## What GhostRecipes does not do

- It does not execute steps, shell commands, or scripts. Ever, in v0.1.
- It does not call any model, network, or external service. Local only.
- It does not approve anything. Gates in a recipe are words a human
  checks, not permissions the tool grants.
- It does not track runs or store history in v0.1. You render a
  checklist, you work the checklist.
- No accounts, no telemetry, no paid layer decided.

Prepared for Ghost Developer Studio, October 2026. Pricing and any
public release are not decided yet.

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
