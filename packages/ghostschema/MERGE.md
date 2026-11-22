# GhostSchema — MERGE (harden + polish + deepen)

Date: 2026-10-18. Base: pristine `~/workspace/ghostschema/` (never edited).
Merge order, as instructed: harden, then polish, then deepen.
Merged tree: `~/workspace/.improve-2026-10-18/ghostschema/merged/`
(fresh copy of pristine, `__pycache__` / `.pytest_cache` excluded).

## Final test counts

| Tree | Suite (`python3 -m pytest -q`) |
| --- | --- |
| Pristine baseline (per all three IMPROVE.md files) | 51 passed |
| harden lane | 65 passed (51 + 14 new in `tests/test_hardening.py`) |
| polish lane | 51 passed (documentation only, no tests added) |
| deepen lane | 57 passed (51 + 6 new in `tests/test_implicit_refs.py`) |
| **merged** | **71 passed, 0 failed** (51 + 14 + 6, in 49.13s) |

Merged passes at least the best lane (harden, 65) and has zero new
failures versus every lane; the counts are exactly additive.
No lane suites were re-run separately — all three IMPROVE.md files
state their counts, and the merged count reconciles exactly with them.

## Files from only one lane (copied from that lane)

- harden: `tests/test_hardening.py` (new file)
- deepen: `tests/test_implicit_refs.py` (new file)
- polish: `examples/README.md`, `src/ghostschema/__init__.py`,
  `src/ghostschema/__main__.py`, `src/ghostschema/terms.py`,
  `src/ghostschema/tokens.py`

## Files changed by multiple lanes (three-way hand-merged)

Merged with `git merge-file` (current = earlier lanes applied,
base = pristine, other = next lane), then verified by grep that every
lane's distinctive change is present and no duplicate logic remains:

- `src/ghostschema/bundle.py` — harden + polish + deepen, clean merge.
  Harden: `write_bundle` OSError → SchemaError wrap. Polish: docstrings
  on `build_manifest` / `render_schema_md` / `write_bundle`. Deepen:
  unresolved listing in SCHEMA.md shows the `via` construct.
- `src/ghostschema/cli.py` — harden + polish + deepen, clean merge.
  Harden: slice refuses any bundle artifact path that resolves to the
  input spec (symlinks included); `main()` converts RecursionError to
  a clean exit 2. Polish: help text, descriptions, epilogs, docstrings.
  Deepen: summary warning wording "remote reference(s)" (was "$ref(s)").
- `src/ghostschema/jsreduce.py` — harden + polish + deepen, clean merge.
  Harden: `_op_haystacks` skips segment-less `#/` refs. Polish:
  docstrings on `list_operations` / `component_entries` /
  `slice_openapi` / `slice_jsonschema`. Deepen: missing-local warning
  wording broadened to "local references".
- `src/ghostschema/refs.py` — harden + polish + deepen, clean merge.
  Harden: list-index pointer segments must be short ASCII digits
  before `int()`. Polish: docstrings on `is_local_ref` /
  `is_external_ref` / `escape_part` / `make_pointer`. Deepen:
  `iter_implicit_refs`, `find_operation`, `_name_candidate`, and
  `closure()` following implicit refs via shared follow/record helpers.
- `src/ghostschema/graphql.py` — harden + polish, clean merge.
  Harden: same-line definition anchor after `}`, single-line string
  strip no longer crosses newlines, schema-block root check compares
  bare type names. Polish: docstrings on `outline_sdl` /
  `render_outline_md`.
- `src/ghostschema/loader.py` — harden + polish, clean merge.
  Harden: UTF-8 BOM stripped after decode (sha256/size still raw),
  read OSError and JSON RecursionError wrapped as SchemaError.
  Polish: docstrings on `LoadedSpec` / `_looks_like_yaml` / `load_spec`.
- `src/ghostschema/mcp_server.py` — harden + polish, **one conflict,
  resolved by hand (see below)**.
- `README.md` — polish + deepen, clean merge. Polish: Install section,
  selection-mode table, exit codes, expanded bundle/MCP docs. Deepen:
  paragraph on implicit-reference reachability (`discriminator.mapping`,
  Link `operationId`/`operationRef`, `via` treatment) — verified
  present in the merged README under "Remote references are never
  fetched".

All other files are byte-identical to pristine (including `LICENSE`,
`pyproject.toml`, fixtures, and the original tests).

## Conflicts and how they were resolved

1. `src/ghostschema/mcp_server.py`, `handle()` — the only conflict.
   Both lanes inserted text immediately after `def handle(request):`
   at the same location: harden inserted the non-object-request guard
   (returns a -32600 error instead of crashing the server), polish
   inserted the function's docstring. Resolution: keep BOTH — polish
   docstring first, then the harden guard — with no other change.
   The rest of the function merged cleanly and contains both lanes'
   other work (harden: non-string method, null/non-object `params`
   and `arguments` normalisation; polish: `_cap`/`serve` docstrings
   and expanded tool descriptions / argument schemas). No harden fix
   was dropped, and no duplicate logic remains. Verified: file has no
   conflict markers and compiles.

No other file conflicted; every other multi-lane file merged cleanly
in disjoint regions (harden = code, polish = docstrings/help,
deepen = wording / one render line / refs additions).

## Notes / anything suspicious

- No `IMPROVE.md` is present in the merged tree (lane files were
  applied file by file; none were copied in).
- The polish lane copy lacked the pristine `build/` directory and
  `src/ghostschema.egg-info/`; the merged tree retains the pristine
  copies, as it started from pristine. As the harden lane noted,
  `build/lib/` is a stale build artifact and was not regenerated;
  the test suite runs from `src/`.
- Deepen's documented limit is preserved as documented behaviour,
  not treated as a defect: a `discriminator` without a `mapping`
  (name-equals-subtype convention) is still not followed, because
  there is no explicit target to follow without guessing.
- Nothing was pushed to GitHub; the pristine tree was never edited.
