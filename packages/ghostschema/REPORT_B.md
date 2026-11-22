# GhostSchema v0.1 - Agent B report (tests, README, examples)

Ownership respected: only `tests/**`, `README.md`, `examples/**`, and this file were written. No edits to `PLAN.md`, `src/**`, or `pyproject.toml`. No core code was fixed by Agent B; the one core defect found was documented here and fixed by Agent A in `src/**` during the run (see D1).

## Final result

```
python3 -m pytest tests -q   ->   45 passed, 0 failed, 0 skipped
```

Run twice against the final core tree with identical results (15-18s per run). CLI discovery in the suite: `GHOSTSCHEMA_CMD` env override, then a `ghostschema` script on PATH, then `python -m ghostschema` with `PYTHONPATH=src`. The final runs used the `python -m` route against Agent A's `src/ghostschema/` (cli.py present, `--help` lists slice / inspect / mcp, matching the PLAN contract).

Breakdown: fixtures 10, inspect 4, OpenAPI slicing 9, external refs 6, refusals 5, JSON Schema slicing 4, SDL outline 5, MCP 2.

## Delivered

- `tests/helpers.py` - black-box runner + discovery, plus an independent `$ref` walker/pointer resolver so the closure checks do not trust the core's own self-check.
- `tests/test_fixtures.py` - ground truth, no core needed: the A to B to C chain (getPet to Pet to PetDetails to Tag), the unrelated orders set, planted waste (`LegacyPet`, `AuditRecord`, `Invoice` referenced by nothing), the planted https refs, the SDL type graph with waste type `AuditLog`, YAML fixtures that are not JSON, the Swagger 2.0 fixture.
- `tests/test_inspect.py`, `tests/test_slice_openapi.py`, `tests/test_slice_jsonschema.py`, `tests/test_external_refs.py`, `tests/test_refusals.py`, `tests/test_sdl_outline.py`, `tests/test_mcp.py` - behavioural tests against the real CLI.
- `README.md` - plain words, honest limits (reading aid not a contract, lexical task matching, estimates, closure proved but spec correctness not, SDL outline-grade), no em dashes.
- `examples/` - `petstore-openapi.json` (mid-size OpenAPI fixture, same file as the test fixture), `schema.graphql` (SDL sample), `README.md` walkthrough. Every command in the walkthrough was run verbatim against the final core and produced the claimed output.

## Hard rules, pinned by tests

- **Reduced JSON parses and closes**: every reduced output from every fixture is reparsed and every local `$ref` is resolved inside the reduced document by the test suite's own resolver. All close.
- **External http `$ref` listed unresolved, never fetched**: slicing `Order` / `listOrders` / `Widget` succeeds offline, the money/materials URLs appear in the manifest unresolved list with their referrer pointers (`#/components/schemas/Order/properties/total`), and the refs stay visible in the reduced spec. Slicing `getPet` (which never reaches the orders surface) reports no unresolved money ref and emits no remote refs.
- **YAML refused**: `.yaml` extension and YAML content under a `.json` name both exit 2 with "yaml" in the message, on `slice` and on `inspect`. Swagger 2.0 exits 2 naming swagger/2.0.
- **SDL labelled outline**: "outline" appears in `outline.json` content, in `OUTLINE.md`, and in the manifest `treatment` field; no `.graphql`/`.gql` file is emitted in any SDL bundle.
- **Inputs byte-identical**: sha256 snapshots of all six fixtures are asserted unchanged after slice, inspect, and refusal runs.

## Defects found

### D1 (core, FOUND by this suite, FIXED by Agent A mid-run, re-verified green)

Against the first complete core tree, 7 tests failed with one root cause: selecting a single operation failed the core's own closure check and exited 2.

- `slice petstore.json --select getPet` -> exit 2: `internal closure check failed on the reduced document: #/paths/~1pets~1{petId}/parameters/0 -> #/components/parameters/PetId does not resolve`
- `slice petstore.json --select listOrders` -> exit 2: `#/paths/~1orders/post/requestBody/content/application~1json/schema -> #/components/schemas/OrderInput does not resolve`

File-level evidence (pre-fix `src/ghostschema/jsreduce.py`, `_reduce_openapi`): keep prefixes were built from pointer prefixes, so selecting one operation marked its whole path item kept (`whole = (kind, path) in keep_prefixes`), and the reducer copied all non-method keys of the path item (including the path-level `parameters` array) plus sibling operations into the output, while reachability seeds covered only the selected operation's own subtree. Sibling-operation refs (`OrderInput`) and path-level parameter refs (`PetId`) were therefore emitted but never followed, and the core's closure self-check correctly refused to ship the bundle. The PLAN explicitly promises kept path items "with their path-level parameters", so this was a core defect, not a fixture quirk. Credit where due: the failure was loud (exit 2, named pointer), never a silently broken spec.

`src/ghostschema/jsreduce.py` was modified by Agent A at 13:37 UTC during this session; after that change the same commands exit 0, `--select getPet` keeps exactly {getPet; Pet, PetDetails, Tag, PetStatus, Error; parameters/PetId, responses/NotFound} and drops the other 9 schemas by name, and the reduced spec closes with zero dangling refs by the suite's independent resolver. Full suite then passed twice (45 passed). Interim counts against the in-flight core, for the record: 33 passed / 12 failed (first full run, including my own shape mismatches below), 37 / 8, 38 / 7 (only D1 remaining), 45 / 0 (final).

### Test-side corrections (Agent B's own bugs, fixed in tests only)

1. First runs assumed flat manifest lists. The real manifest emits `kept`/`dropped` as per-kind objects and unresolved refs under `unresolved_refs` as `{ref, from}` objects. `helpers.manifest_lists` now normalises dict-of-lists and both key spellings; no assertion was weakened.
2. The SDL dropped-types test asserted the string `AuditLog` appears nowhere in `outline.json`. The outline artifact legitimately names dropped types in its own dropped listing. The test now asserts `AuditLog`/`Order` are absent from the outline's kept `types` list, which is the actual rule.

## Assumptions recorded

- CLI contract taken from PLAN.md and confirmed against the landed core: `ghostschema inspect <spec>`, `ghostschema slice <spec> [--task ...] [--select <comma-separated ids>] [--all] [-o <bundle-dir>]`, `ghostschema mcp`. Bundle files per PLAN: `spec.json`, `manifest.json`, `SCHEMA.md`; SDL: `outline.json`, `OUTLINE.md`, `manifest.json`. All confirmed present in real bundles.
- Manifest field names `original_tokens` / `sliced_tokens` / `treatment` are asserted exactly (PLAN names the treatment values; the token field names matched the landed core). Kept/dropped/unresolved contents are matched by substring over normalised entries, since the PLAN fixes their meaning, not their entry shape.
- Interpretation: a remote `$ref` that is dropped along with its containing surface is not expected in the unresolved list (unresolved describes refs that survive into the output). The landed core behaves this way and the test pins it.
- Token honesty (manifest original estimate equals the estimator applied to the untouched source text) is asserted by shape only (positive integers, sliced < original on the waste fixture, `token_method` stamped: the final tree reports the GhostSlice estimator). Byte-exact estimator replication is the core's own test territory; Agent B did not duplicate the estimator.
- MCP argument name for `schema_inspect` was taken as `path`; the tools/list and summary-only tests pass against the landed server.

## Gates held

Stdlib only in tests (pytest + stdlib), local only, no network (the suite's external-ref cases run against example.com URLs that are never fetched; runs complete in seconds offline), no push, no PyPI/publish, no announcements, no spend.
