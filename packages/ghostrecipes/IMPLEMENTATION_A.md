# GhostRecipes v0.1 - Implementation A (core builder)

Built Oct 14, 2026 from the PLAN.md written in this same dispatch
(PLAN.md in Slice format, mirroring ~/workspace/ghostverify/PLAN.md).
Agent A scope: PLAN.md, src/**, pyproject.toml, this file.
tests/**, README.md, and examples/** (starter recipes) are Agent B's
and were not edited. Zero-dependency Python stdlib only. Local only.
No push, publish, announcement, or spend.

## The central rule, and how the code enforces it

Recipes are DATA ONLY in v0.1. GhostRecipes never runs a recipe step,
a command hint, or any other content found in a recipe file.

- There is no runner at all: a source scan of src/ finds no
  process-spawning, network, or dynamic-code tokens (no subprocess,
  os.system, popen, socket, urllib, http.client, requests, eval, or
  exec tokens anywhere under src/).
- `command_hint` is a step field that exists only to be *printed*,
  in a fenced block labelled "run manually - GhostRecipes does not
  run this", during render.
- The format keeps execution hooks out structurally: unknown keys at
  top level, step level, and input level fail validation by name, so
  a field like `auto_run`, `command`, or `script` cannot enter a
  valid recipe (verified in smoke test 4c).
- Proven behaviourally in smoke test 2: a step whose command hint was
  `touch /tmp/gr-smoke/SHOULD_NOT_EXIST` was validated, shown,
  listed, rendered, and exported; the file was never created.

## What was built

Package `ghostrecipes` 0.1.0 under src/ghostrecipes/:

- recipe.py - the format and validator.
  - Canonical file: `<id>.recipe.json`, one JSON object. Markdown
    variant: a `.recipe.md` file whose recipe is the single fenced
    json block it contains.
  - Top level: id (slug), name, version (MAJOR.MINOR.PATCH),
    description, steps (required); tags, author, date (YYYY-MM-DD),
    category, tools, inputs, notes (optional). Unknown keys rejected.
  - Steps: id (unique slug), title, kind (one of manual, check, run,
    review, approve, note; `run` is a label for the follower, never
    an instruction to this tool), plus optional detail,
    command_hint, tools, gate, repeat.
  - Inputs: name (unique identifier), description, required,
    default. `{{name}}` placeholders in description/detail/
    command_hint/gate text: undeclared placeholder is a warning,
    declared-but-unused is a warning.
  - Data-only file rules: only .json/.md/.txt, executable permission
    bit fails, shebang fails.
  - Library discovery, in order: --library, $GHOSTRECIPES_LIBRARY,
    ~/.ghostrecipes, ./recipes, the checkout's bundled recipes/.
  - find_recipe_files and resolve_recipe (by file, folder, or id;
    invalid files are listed as INVALID, never silently skipped).

- render.py - render to a human checklist / prompt file.
  Title, id + version + file sha256, a standing "this is a checklist,
  not a program" notice, description, inputs table (defaults applied,
  --var overrides), numbered `- [ ]` steps with detail, repeat,
  tools, gate, and command hints in labelled fenced blocks, notes,
  and an "Unresolved placeholders" section listing anything left
  visible instead of guessed.

- packio.py - data-only export/import, GhostPacks style.
  - Export: recipe file plus manifest.json (format stamp
    `ghostrecipes-pack`, tool version, recipe id + version, per-file
    sha256). Refuses an invalid recipe and a non-empty target
    without --force.
  - Import: verifies manifest format, every entry (flat file name
    only: absolute or `..` entries rejected), every sha256, and
    every recipe's validity, rejects symlinks and any non-data file
    anywhere in the pack, and only then copies into the library.
    Any failure writes nothing. A library name collision without
    --force writes nothing.

- authoring.py - create: scaffolds a valid v0.1.0 recipe (--id,
  --name, --description, --tags, --steps "Title; Title" with
  slugified unique step ids), validates before writing, refuses to
  overwrite without --force.

- cli.py - subcommands: create, list [--json], show [--json],
  validate (file, folder, or id), export, import, render
  [--var name=value, repeatable]. Exit codes: 0 ok, 1 validation
  failure, 2 usage or config errors. --version.

pyproject.toml: setuptools, requires-python >=3.10, no
dependencies, console script `ghostrecipes`.

## Smoke test (run, recorded)

Environment: PYTHONPATH=src, python3 -m ghostrecipes (Python 3.12.3).

1. create: scaffolded `marathon-loop` from --steps titles; output
   validated clean, with placeholder warnings for {{project}} /
   {{owner}} (used, undeclared), exactly as designed.
2. Rich recipe (inputs, gate, repeat, command_hint, tools):
   validate OK; list and show print id, version, sha256, inputs,
   steps. Render with --var tool=GhostRecipes substituted the value
   in description, details, gates, and hints, applied the `owner`
   default (Ryan), and printed both command hints as inert labelled
   text. The hint target file was never created.
3. Export/import round trip: export wrote the recipe plus a
   manifest with sha256 ce45706d...; import into a fresh library
   produced a byte-identical file (hash match confirmed).
   Re-import without --force: exit 2, nothing written.
4. Negative cases, each failing with the reason named and nothing
   imported/written:
   a. Tampered pack file: sha256 mismatch, exit 2.
   b. Manifest entry `../evil.recipe.json`: unsafe entry, exit 2.
   c. Recipe with a step key `auto_run`: validate exit 1, unknown
      key named.
   d. Pack containing an executable run.sh: non-data file, exit 2.
5. Markdown recipe: a .recipe.md with one fenced json block
   validated OK and rendered to a checklist.
6. Unresolved placeholders: rendering the marathon-loop scaffold
   listed {{owner}} and {{project}} in an Unresolved placeholders
   section, left visible, never guessed.
7. Install check: pip install of the checkout (with
   --no-build-isolation against the system setuptools; the sandbox
   cannot fetch a build backend) succeeds into a target dir with
   the package and console script present.
8. Cross-check with Agent B's landed work: all three starter
   recipes in examples/ (slice-marathon-loop, audit-improve-verify,
   creator-pitch-draft-first) validate OK under this core, and
   Agent B's full test suite passes against it: 25 passed.

## Honest notes

- Placeholder discipline is warnings, not errors, by design, so a
  draft recipe validates while being written; render is where
  unresolved values become visible. If Ryan wants strict mode, it
  is a one-flag change in validate_data.
- Import copies recipe files flat into the library root; nested
  pack subfolders are rejected by the flat-name entry rule in v0.1.
- The bundled recipes/ folder at the checkout root is currently
  empty (Agent B placed the starter recipes in examples/); library
  discovery already includes both locations, so starters moved into
  recipes/ later will be found with no code change.
