# GhostRecipes v0.1 polish round
Oct 14, 2026. One owner for the whole folder. Loop: audit first,
then two distinct improvement passes, demonstrate-then-fix for
every change. Baseline on arrival: 25 passed. Final: 42 passed
(25 original plus 17 new regression tests in tests/test_polish.py).
No version bump, no push, no publish, no announcements.

The central rule held throughout: recipes stay data only. No runner
was added, no execution path was touched, and a source scan of src/
still finds no process-spawning, network, or dynamic-code tokens.

## Audit findings (each demonstrated before any fix)

Findings were demonstrated with a throwaway probe script against
the shipped CLI, then re-run after the fixes.

1. `list --json` did not print JSON. The `library: ...` header was
   printed to stdout before the JSON array, so any script parsing
   stdout failed. Demonstrated: json.loads on the output raised.
2. Library discovery double-listed recipes. Discovery deduped
   folders by literal string, so `--library recipes` run inside a
   project also matched `./recipes` in the fallback list under its
   absolute spelling, and the same recipe printed twice.
3. Import pack stray-file check was suffix only. A pack carrying
   an extra `notes.txt` with a shebang line and the executable bit
   set imported cleanly (exit 0), even though the pack module
   promises to reject executable and shebang files anywhere in a
   pack. The file was never copied into the library, but the pack
   was certified as clean when it was not.
4. Import trusted the manifest's recipe list. The result returned
   `manifest["recipes"]` unverified, so a pack whose manifest
   claimed a different recipe id still reported that claim after
   import. Duplicate manifest entries for the same path were also
   accepted.
5. `export -o <existing file>` crashed with a Python traceback
   (exit 1) instead of a clean error. The same crash shape waited
   in `import` if the library path was an existing file.
6. Validator accepted impossible dates. `date: "2026-13-99"`
   matched the YYYY-MM-DD shape and passed.
7. Validator accepted whitespace-only required strings. A recipe
   with `name: "   "` (and the same trick for description and step
   title) passed.
8. Placeholder warnings did not cover what render substitutes.
   Render substitutes `notes`, but the validator never scanned
   notes, so `{{undeclared}}` in notes validated silently and only
   surfaced at render time.
9. Malformed placeholders were invisible. `{{1bad}}` is not a
   valid placeholder, render left it as literal text, and neither
   validate nor render ever mentioned it.
10. Render broke its own Markdown. Three shapes, all shown in
    probe output: an input value of `a|b` split the inputs table
    row into extra columns; a multi-line step detail printed its
    second line at column zero, outside the checklist item; a
    command hint containing ``` closed the render fence early and
    spilled the rest of the hint into the document body.
11. A required input with no value rendered as an empty table
    cell, indistinguishable from an optional input left blank.
12. The marathon starter was missing steps its own plan requires.
    The PLAN verification bar names build, audit, improve twice,
    verify, push, release. The starter ended at verify: no push
    step, no release step, only a note saying a push is not a
    release.
13. README never documented library discovery at all, which is
    exactly why the fallback scanning surprised Agent B during the
    build. Exit codes, pack rules, and warning behaviour were also
    undocumented. Separately, examples/WALKTHROUGH.md said `show`
    prints the recipe notes, but `show` did not print notes or
    category.

## Pass 1: pack safety, validator strictness, output integrity

- packio: the stray-file sweep now applies the full data-only
  check (suffix, executable bit, shebang) to every file in the
  pack folder, listed in the manifest or not. Finding 3 closed.
- packio: duplicate manifest entries are rejected by path, and
  import reports the recipe ids verified from the pack files,
  not the manifest's claim. Finding 4 closed.
- packio: export to an existing non-folder path, and import with
  a library path that is an existing file, now raise the normal
  clean error (exit 2, no traceback). Finding 5 closed.
- recipe: date validation now requires a real calendar date, not
  just the right shape. Finding 6 closed.
- recipe: name, description, and step title must be non-blank
  after stripping whitespace. Finding 7 closed.
- recipe: the placeholder scan covers exactly the fields render
  substitutes (description, notes, step title, detail,
  command_hint, gate), and malformed `{{...}}` segments are now
  named in a validation warning. Findings 8 and 9 closed.
- cli: in `--json` mode the library header goes to stderr, so
  stdout is parseable JSON. Finding 1 closed.
- recipe: library discovery decision. The fallback scanning is by
  design (the plan specifies an ordered fallback list, and import
  already targets one folder only), so it was tightened, not
  removed: dirs dedupe by resolved path, and find_recipe_files
  dedupes files by resolved path, so one physical recipe is never
  listed twice. The behaviour is now documented in the README.
  Finding 2 closed.

## Pass 2: render clarity, starter quality, README accuracy

- render: inputs table cells escape pipes and flatten newlines,
  so values cannot break the table. Finding 10a closed.
- render: multi-line detail and gate text is emitted with
  continuation lines indented to the bullet, staying inside the
  checklist item. Finding 10b closed.
- render: the command hint fence is one backtick longer than the
  longest backtick run inside the hint, so a hint containing ```
  cannot close the fence early. Finding 10c closed.
- render: a required input with no value now shows
  `(not provided)` in the Value used column, and is still listed
  in Unresolved placeholders. Finding 11 closed.
- examples: slice-marathon-loop gained the two missing steps,
  in order after verify: `push` (run, gate: only verified work
  is pushed, detail states a push is not a release) and
  `release` (approve, gate: separate approval for any release,
  publish, or announcement). Finding 12 closed.
- cli: `show` now prints category and notes, matching what the
  walkthrough already claimed. Finding 13 partially closed.
- README: new sections for library discovery (ordered list,
  fallback behaviour, dedupe, import exception), exit codes and
  warnings, and pack verification rules. Finding 13 closed.

## Regression tests

tests/test_polish.py, 17 tests, one or more per fix: parseable
`list --json` output; text mode header kept; two-spelling library
listed once; stray executable shebang txt rejected with nothing
imported; duplicate manifest entries rejected; import result
reports verified ids against a lying manifest; export to a file
is a clean exit 2 with no traceback; impossible date rejected,
real date accepted; whitespace-only name rejected; placeholder
in notes warned; malformed placeholder warned by name; pipes
escaped in the render table; required input marked
`(not provided)`; hint backticks cannot close the render fence;
multi-line detail indented; marathon starter orders push and
release after verify with an approve gate on release.

## What was left alone

- Library file symlinks: a recipe file that is a symlink inside a
  user's own library folders is still followed by list and show.
  Reasoning: the library is the user's own trusted folder, unlike
  an imported pack, which still rejects symlinks outright.
  Symlinked directories are not descended by discovery (checked:
  no loop, no escape), and resolved-path dedupe means two links
  to one file list it once.
- A plain `.txt` file validates when passed to `validate`
  directly, though discovery only indexes `.recipe.json` and
  `.recipe.md`. The data-only rules allow .txt as a data suffix
  by design; direct-path validate staying permissive matches how
  a folder or id is resolved, and no test or doc promises
  otherwise.
- Placeholder strictness stays warnings, not errors, as recorded
  in IMPLEMENTATION_A.md. A draft recipe should validate while
  being written. The polish round widened what is warned about
  instead of changing the severity Ryan's design already chose.
- Input descriptions, tools, and repeat text are not placeholder
  scanned, because render prints them verbatim. Scanning them
  would warn about text that is never substituted.
- The lying-manifest fix is observable in the import result
  (unit tested). The CLI import output never printed the
  manifest's recipe list, so no CLI text changed.
- Version stays 0.1.0. Releases remain Ryan's separate gate.

## Verification

- `python3 -m pytest tests -q` in ~/workspace/ghostrecipes:
  42 passed (25 original, 17 new), run at the end of the round.
- The audit probe re-run after fixes: list JSON parses, two
  spelling library lists once, stray executable pack rejected
  (exit 2), impossible date and whitespace name rejected
  (exit 1), notes and malformed placeholders warned, render
  table row shows the escaped pipe, detail continuation is
  indented, the hint renders inside a four-backtick fence, and
  export to a file exits 2 with no traceback.
- Em dash scan: no em dash character in README.md, examples/,
  src/, or this file.
