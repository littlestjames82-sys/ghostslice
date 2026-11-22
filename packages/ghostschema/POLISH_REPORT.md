# GhostSchema v0.1 - Polish report
Polish round Oct 14, 2026, at Ryan's "Polishing". Sole folder owner for this round. In-tree only: no version bump (pyproject still 0.1.0), no push, no publish, no announcements, no spend. Stdlib only, local only.

## Audit first
Read PLAN.md, IMPLEMENTATION_A.md, REPORT_B.md before touching code. Baseline suite on the untouched tree: **45 passed** (matches the parent-verified count). The documented limits were the candidate list; the SDL body parser was the top seed because it was the only limit that could silently corrupt a result (a dropped type) rather than merely degrade one.

## What changed

### SDL body scanning: token stream instead of line by line
`src/ghostschema/graphql.py`: `_parse_fields` no longer iterates body lines and matches one field per line. It scans the body as a token stream, so every field in a body is found wherever it sits on a line. Supporting pieces, all in the same file:

- After a field's type, directive applications (`@name` plus its balanced argument list) and a default value (`= ...`, balanced `{...}` / `[...]` or one scalar token) are skipped before scanning resumes, so neither can swallow or masquerade as the next field.
- `_parse_args` now splits the argument list on top-level commas (bracket-depth aware) and anchors one `name: type` per piece, instead of running a global finditer. A `name: type` pair inside an argument's default object is no longer mistaken for an argument.
- `_parse_values` (enum values, body-written union members) strips directive applications first and collects every name token, instead of taking only the first token of each line that contained no colon. A value carrying a directive (whose arguments contain colons) is no longer dropped wholesale.

Demonstration, same compact fixture before and after (`type Pet { id: ID! name: String! status: PetStatus tag: Tag friend: Pet }`, one-line enum, `--select Pet`):

- Before: kept types = Pet only, with fields `[id]`; Tag and PetStatus were dropped as unreachable, because the fields naming them sat after the first field on the line. Enum outline would have listed only the first value per line.
- After: Pet fields `[id, name, status, tag, friend]`, Tag kept with `[id, label]`, PetStatus kept with values `[AVAILABLE, PENDING, SOLD]`; dropped = DateTime, Query, Unused (genuinely unreachable from Pet).

### Regression tests added
`tests/test_sdl_compact_bodies.py`, 6 tests, black-box CLI style like the rest of the suite, no existing assertion touched:

1. Fields declared on one line are all found, in order.
2. Types reachable only via same-line fields are kept; the waste type stays dropped.
3. Enum values declared on one line are all listed.
4. A directive after a field type does not swallow the next field; a deprecated enum value mid-line is still listed and adds no phantom value.
5. An argument whose default is an object literal contributes exactly that one argument (the object's inner `name: type` pair is not an argument).
6. A multi-line default object on an input field adds no pseudo-fields (its inner keys stay out of the field list), fields declared on one line inside the referenced input are both found, and a one-line `schema { ... }` block lists both root operations.

Pin check: all 6 new tests fail against the pre-polish parser (verified by temporarily restoring the line-oriented implementations: 6 failed) and pass against the polished one.

## Test counts
- Before: 45 passed, 0 failed.
- After: **51 passed, 0 failed** (45 original, untouched, plus the 6 new). Full suite run on the final tree.

## What was deliberately left alone
- **Task-term selection (terms.py) stays purely lexical.** Evaluated the obvious tweak (better plural stripping in `ident_tokens`, e.g. `statuses` currently also yields `statuse`). Under the current scoring, selection is binary (score above zero) with no top-N cut, and the existing prefix rule already scores a plural-only match at half weight, which is still above zero, so the tweak provably changes no selection outcome on any input while touching scoring shared by all three formats. Not worth regression risk for zero outcome change. PLAN.md already documents lexical selection as an accepted v0.1 limit with `--select` as the precise route.
- **Directive definitions** remain counted and named in manifest warnings, not outlined. That is plan-specified behaviour, not a defect.
- **Nested `$defs` inside a kept JSON Schema def** remain carried whole and not separately sliceable. A feature, not a polish fix; out of this round's scope.
- **Tiny-SDL negative savings** (outline bundle larger than a tiny source) are the fixed cost of the mandated outline labelling; the manifest already reports the true figure honestly.
- **IMPLEMENTATION_A.md** still describes the parser as line-oriented in its known-limits section. It is the dated build record of the original build and was left as history; this report is the record of the change. README.md makes no line-oriented claim (its "outline-grade" wording remains accurate), so it needed no edit.

## Gates held
No existing test assertion weakened or deleted (6 tests added, 0 modified). Version unchanged at 0.1.0. Changes confined to `src/ghostschema/graphql.py`, the new test file, and this report. No network, no push, no PyPI, no announcements, no spend.
