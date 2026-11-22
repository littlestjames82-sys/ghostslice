# GhostRecipes - Agent B Report (tests / README / examples)
Prepared Oct 14, 2026. Scope owned and edited by Agent B only:
tests/**, README.md, examples/**, this file. src/**, pyproject.toml,
and PLAN.md were read (read-only, after Agent A's core landed) but
never edited.

## Result: PASS, 25/25 tests, run twice
`python3 -m pytest tests -q` from ~/workspace/ghostrecipes:
- Final state: **25 passed, 0 failed**, twice (13.58s, 4.52s).
- Breakdown: examples data 6, validate 11, never-executes 2,
  list/show/render/export/create 6.

## Honest run history
- My first examples draft used an assumed schema (title / gates /
  outputs top-level keys, step `instructions` / `expected`, kind
  `command`) written before Agent A's core existed. When the core
  landed, its PLAN/schema differed on every one of those points, so
  the draft examples would have failed validation. They were rewritten
  to the landed schema (see below) and renamed to the canonical
  `<id>.recipe.json` form. The first full-suite run against the real
  core, after that alignment, was already 25/25 - there was no
  intermediate failing run of the aligned suite to report.
- No core defects were found. One CLI behaviour worth knowing: `list`
  always also scans the fallback library dirs (~/.ghostrecipes, the
  cwd `recipes/` folder, and the bundled checkout `recipes/` folder)
  in addition to `--library`, by design in default_library_dirs.

## Contract the tests drive (assumed, then aligned to the landed core)
- Commands, confirmed from src/ghostrecipes/cli.py:
  `create --id ID --name NAME -o FILE [--description] [--tags]
  [--steps "Title; Title"] [--force]` (scaffolds at version 0.1.0),
  `list [--library DIR] [--json]`, `show <id-or-path> [--json]`,
  `validate <path-or-id-or-folder>`, `export <id-or-path> -o DIR`
  (recipe file + manifest.json with sha256, recipe id, version),
  `import <pack-folder> [--library DIR]` (covered in README /
  walkthrough; no dedicated test, export is the tested direction),
  `render <id-or-path> [-o FILE] [--var name=value ...]`.
- Format, confirmed from src/ghostrecipes/recipe.py: top-level keys
  are an allowlist (id, name, version, description, steps, tags,
  author, date, category, tools, inputs, notes); step keys are an
  allowlist (id, title, kind, detail, command_hint, tools, gate,
  repeat); kinds are manual / check / run / review / approve / note;
  inputs use {{name}} placeholders in text. Unknown keys fail by name.

## Safety test (the v0.1 central rule)
tests/test_never_executes.py builds a valid recipe whose steps carry
`command_hint` and detail text that would create a sentinel file if
any shell ran them, then runs validate, show, list, render, and
export against it. The sentinel never exists. Companion test in
test_validate.py: execution-hook keys (`command`, `script`,
`on_load`, `autorun`) at top level, and `command` inside a step, are
all rejected by validate - hooks cannot enter the format at all.

## Examples delivered (examples/, all validate OK against the core)
- slice-marathon-loop.recipe.json (7 steps): define goal, slice
  context (command_hint for the Slice export), build, audit, improve
  once, improve twice (a separate step, not a repeat flag), verify
  before moving on (step gate). Notes hold the marathon gates:
  no publish, no announcement, no paid spend without separate
  approval; a push is not a release.
- audit-improve-verify.recipe.json (5 steps, exact order audit,
  improve-1, improve-2, verify, report, pinned by test): two
  improvements must be two separate changes (step gate), verification
  requires evidence.
- creator-pitch-draft-first.recipe.json (6 steps): verify creator,
  pick one lead, draft, approve gate, send verbatim, watch for reply.
  Draft-before-approval ordering is pinned by test, as are the gates
  "Nothing is sent without approval" and "No em dashes in any copy
  that will be posted or sent". A data test also asserts no em dash
  character appears anywhere in examples/ or README.md (the only
  occurrence in B-owned files is the literal constant in that test).

## README / walkthrough
README documents the landed CLI exactly, the allowlist format, the
rendered checklist shape (with sha256 line and run-manually command
hints), and the does-not-do list (never executes, no network, no
approvals granted, no run tracking in v0.1). examples/WALKTHROUGH.md
walks validate / list / show / render with --var / create / export
by hand, all offline.

## Gates held
Local only, no push, no publish, no announcements, no spend.
Nothing in B's work executes a recipe step.
