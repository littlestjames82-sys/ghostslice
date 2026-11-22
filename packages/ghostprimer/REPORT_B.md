# GhostPrimer v0.1 - Agent B report (tests, README, examples)

## Result

Final run against Agent A's real core, run twice with identical results:

```
PYTHONPATH=src python3 -m pytest tests -q
28 passed, 3 failed, 0 skipped  (31 tests)
```

All 3 failures are genuine core defects against PLAN.md hard rules and
its verification bar (D1-D3 below). No core code was edited by Agent B;
the failing tests are kept strict on purpose. Per file:

- tests/test_fixtures.py: 5 passed (ground truth, no core needed)
- tests/test_build.py: 8 passed, 2 failed (D2, D3)
- tests/test_memory.py: 4 passed
- tests/test_recall_bundle.py: 1 passed (real GhostRecall bundle)
- tests/test_exclusions.py: 2 passed (outside-root and private-memory
  symlink refusals both hold, sentinels never reach the bundle)
- tests/test_secrets.py: 0 passed, 1 failed (D1)
- tests/test_check.py: 5 passed (including the `ghostslice check`
  cross-run: a Primer bundle validates under GhostSlice, ok true)
- tests/test_budget_doctor_mcp.py: 3 passed

## Defects found (core, Agent A territory)

### D1 - Planted secret in a memory file is exported verbatim (hard rule)
PLAN.md: a flagged memory item is blocked, recorded, and its text does
not appear in PRIMER.md. Reality: building
tests/fixtures/secretmem_project (its AGENTS.md carries a synthetic
sk- shaped key in a "Deploy notes" section) produces a bundle whose
PRIMER.md contains the key verbatim under
`### Deploy notes [AGENTS.md:7]`, and the build summary reports
`blocked: 0`. Verified by hand against a manual build as well as by
tests/test_secrets.py::test_secret_memory_item_blocked. The secrets
guard is not being applied to fallback memory extracts (or its findings
are not acted on). Suspected core area: src/ghostprimer/memory.py with
src/ghostprimer/secrets.py. This is the one failure I would gate the
release on.

### D2 - Unreferenced module is sliced in; not-included list is empty
PLAN.md verification bar: a file nothing imports and no entry point
references is not included and appears in the not-included list.
Reality on tests/fixtures/starter_project: the build reports
`files: 7` (every Python file in the project) and
`not included: 0`; PRIMER.md contains a full
`### src/widgetforge/orphan.py (mode: signatures, ast)` section and the
Not included section reads "(nothing recorded)". The starter selection
appears to include everything that fits the budget instead of entry
points plus highest fan-in only. Test:
tests/test_build.py::test_orphan_not_sliced_but_named_not_included.

### D3 - README extract omits the first paragraphs
PLAN.md: the README extract is title, headings, and the first paragraph
under each heading. Reality: the bundle's README section lists only the
headings (`# WidgetForge`, `## Usage`, `## Layout`) with no paragraph
text at all, even though the section's own heading in PRIMER.md reads
"README extract (verbatim headings + first paragraphs)". The starter
fixture's Usage paragraph ("Heat the furnace, place the blank...") is
absent. Test: tests/test_build.py::test_readme_extract_in_primer.

## What held

- Exclusion hard rules pass: an AGENTS.md symlinked outside the project
  root and a DECISIONS.md symlinked into a fake HOME's MEMORY.md are
  both refused with the refusal recorded; neither sentinel appears in
  the bundle.
- Recall consumption passes end to end with a real GhostRecall bundle
  generated at test time: the current decision (D-011) is included
  verbatim, the superseded one (D-010) is absent, and the manifest
  records the recall-bundle path.
- Manifest reconciliation passes: per-file sha256 values match the
  bundled files or the sources, totals are integers and reconcile with
  the per-file sums, and the manifest records the sha256 of PRIMER.md.
- Check contract passes: fresh bundle exit 0, one-line tamper of
  PRIMER.md exit 1, tampered sliced file exit 1, missing bundle exit 2.
- Tiny budget (60 tokens) still writes a bundle, reports the budget
  unmet, and keeps the entry point at outline.
- MCP stdio answers initialize and tools/list with primer_build and
  primer_check.

## Assumptions made (tests written fixture-first against PLAN.md)

- A1: CLI shape is the plan's: `build <project> -o <bundle>`,
  `check <bundle>` with exit codes 0/1/2, `doctor <project>`, `mcp`.
  The landed core matched all of it.
- A2: CLI discovery order is $GHOSTPRIMER_CMD, PATH, then
  `python -m ghostprimer` with PYTHONPATH=src. Sibling CLIs
  (ghostslice check, ghostrecall bundle) are discovered from their
  sibling checkouts and their tests skip cleanly if absent; both were
  present and ran for real in the final run.
- A3: Manifest assertions are tolerant about key placement for memory
  items and the recorded PRIMER.md hash, strict about the Slice-schema
  parts the plan pins (integer totals, per-file token fields, sha256).
- A4: One test-side fix during alignment: the extractive-only test first
  demanded sliced signature lines match source lines byte for byte; the
  core's AST signatures normalise spacing (`int = 900` returns as
  `int=900`), which is still structurally derived, so the comparison
  now ignores whitespace only. Names and arguments must still match a
  real source line. No assertion was weakened for D1-D3.

## Deliverables

- tests/ (8 files, 31 tests) with fixtures: starter_project (known
  entry point, fan-in hub, orphan), recallproj (current + superseded
  decisions), secretmem_project (planted secret in AGENTS.md).
- README.md: plain words, hard rules, honest limits, no em dashes.
- examples/: sample_project plus a walkthrough README (doctor, build,
  read PRIMER.md, check, recall-bundle variant, undo). The walkthrough
  commands were run for real against the landed core: doctor exit 0,
  build exit 0, check exit 0 (ok true).

## Gates held

Stdlib only, local only, no network use, no push, no publish, no
announcements, no spend. Only tests/**, README.md, examples/**, and this
report were written.
