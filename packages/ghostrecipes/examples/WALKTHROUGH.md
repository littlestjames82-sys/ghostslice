# GhostRecipes walkthrough

A worked run through the three starter recipes: validate them, list
and show them, render a checklist, then create and export your own.

Prerequisites: Python 3.10 or newer, and a terminal in the repo root
(the folder containing `README.md` and `examples/`). Everything runs
offline. Recipes are data, so every step below is safe to try:
nothing here runs a recipe step or a command hint.

Tip: every command also accepts `--help`, for example
`PYTHONPATH=src python3 -m ghostrecipes render --help`.

## 1. Validate the starters

```bash
PYTHONPATH=src python3 -m ghostrecipes validate examples/slice-marathon-loop.recipe.json
PYTHONPATH=src python3 -m ghostrecipes validate examples/audit-improve-verify.recipe.json
PYTHONPATH=src python3 -m ghostrecipes validate examples/creator-pitch-draft-first.recipe.json
```

Expected: each line starts with `validate: OK` and the exit code is
0. Try breaking one in a copy (delete the `version` field) and
validate the copy: it should fail, name the problem, and exit 1.

## 2. List and show

```bash
PYTHONPATH=src python3 -m ghostrecipes list --library examples/
PYTHONPATH=src python3 -m ghostrecipes show examples/slice-marathon-loop.recipe.json
```

List shows id and version for each of the three starters. Show prints
the marathon loop in full, including its step gates and its notes:
no publish, no announcement, and no paid spend without a separate
approval.

You can also address a recipe by id instead of by path once its
folder is in the library search list, for example
`show slice-marathon-loop --library examples/`.

## 3. Render a checklist and work it by hand

```bash
PYTHONPATH=src python3 -m ghostrecipes render examples/audit-improve-verify.recipe.json --var target=README.md -o /tmp/audit-checklist.md
cat /tmp/audit-checklist.md
```

You get five checkboxes: audit, first improvement, second improvement,
verify with evidence, report plainly. The `--var target=README.md`
fills the recipe's `{{target}}` placeholder; omit it and the checklist
instead lists `target` under Unresolved placeholders. Work the
checklist yourself. GhostRecipes has done its whole job once the
checklist exists.

## 4. Create and export your own

```bash
PYTHONPATH=src python3 -m ghostrecipes create --id weekly-review --name "Weekly Review" -o /tmp/weekly-review.recipe.json
PYTHONPATH=src python3 -m ghostrecipes validate /tmp/weekly-review.recipe.json
PYTHONPATH=src python3 -m ghostrecipes export /tmp/weekly-review.recipe.json -o /tmp/weekly-review-export
cat /tmp/weekly-review-export/manifest.json   # recipe id, version, and sha256 of the recipe file
```

Edit the skeleton between create and export: give it real steps
(add `--steps "First step; Second step"` at create time, or edit the
JSON directly), then validate again before you share the export with
anyone. To bring a pack back, use
`ghostrecipes import /tmp/weekly-review-export --library my-library/`.

## What to try next

- Render the marathon loop with both of its inputs filled:
  `render examples/slice-marathon-loop.recipe.json --var project=my-project --var goal="ship the fix"`.
- Write a recipe in Markdown form: a `.recipe.md` file containing
  exactly one fenced json block validates and renders the same way.
