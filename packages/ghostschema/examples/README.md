# GhostSchema examples

Two sample specs to try the tool on. Both are fixtures: small enough to read in full, large enough that slicing visibly saves tokens.

All commands below assume `ghostschema` is installed (see the
Install section of the top-level README). From a checkout without
installing, replace `ghostschema` with
`PYTHONPATH=src python3 -m ghostschema` and run from the repository
root. Output directories (`/tmp/...` below) can be any path; the
input file is never modified.

Contents:

- `petstore-openapi.json`: an OpenAPI 3.0 document, reduced to a smaller spec.
- `schema.graphql`: a GraphQL SDL schema, outlined only.
- A standalone JSON Schema walkthrough at the end uses the test
  fixture at `tests/fixtures/parts-schema.json`, since it is the
  smallest complete JSON Schema example in the repository.

## petstore-openapi.json

A mid-size OpenAPI 3.0 document for a fictional pet store API. It is deliberately planted with things a slicer should drop:

- An unrelated orders surface (`listOrders`, `createOrder`, `getOrder`, and the `Order` schema family).
- Waste schemas referenced by nothing: `LegacyPet`, `AuditRecord`, `Invoice`.
- External references: `Order.total` and `OrderLine.unitPrice` both point at `https://example.com/schemas/money.json#/components/schemas/Money`. GhostSchema never fetches it. Slice by the `Order` schema and watch both uses land in the manifest's unresolved list instead.

### Step 1: inspect the spec

```bash
ghostschema inspect examples/petstore-openapi.json
```

This lists the format (`openapi`), all 8 operations (for example
`GET /pets/{petId} (getPet)`), and every component group with its
names: 3 parameters, 2 responses, and 14 schemas. Add `--json` for
the same listing as machine-readable JSON.

### Step 2: slice one operation

```bash
ghostschema slice examples/petstore-openapi.json --select getPet -o /tmp/pet-bundle
```

The summary reports 1 operation kept and 7 dropped. The bundle at
`/tmp/pet-bundle` holds `spec.json`, `manifest.json`, and
`SCHEMA.md`.

The `getPet` bundle keeps the chain `Pet` to `PetDetails` to `Tag`, plus `PetStatus`, the shared `NotFound` response and `Error` schema, and the `PetId` path parameter, and drops the orders surface by name in the manifest.

### Step 3: slice by task wording instead

```bash
ghostschema slice examples/petstore-openapi.json --task "add a pet to the store" -o /tmp/task-bundle
```

Task selection is word matching (see Limits in the top-level
README), so it keeps a broader set than the precise `--select`
run above. Prefer `--select` when you already know the id.

### Step 4: slice by the Order schema and see the remote references

```bash
ghostschema slice examples/petstore-openapi.json --select Order -o /tmp/order-bundle
```

Selecting a schema name keeps that schema family (`Order`,
`OrderLine`, and `OrderStatus`) and no operations. The `Order`
bundle keeps both remote money references visible in the reduced
spec and lists each one as unresolved in `manifest.json`, under
`unresolved_refs`, with the pointer that referenced it. They are
listed, never fetched.

## schema.graphql

A GraphQL SDL schema for the same fictional store. SDL gets the outline treatment only: no reduced `.graphql` file is ever emitted.

```bash
ghostschema inspect examples/schema.graphql
ghostschema slice examples/schema.graphql --select Pet -o /tmp/pet-outline
```

`inspect` lists the types it found and notes that treatment is
outline-only. The slice bundle holds four files: `outline.json` and
`OUTLINE.md` (the outline itself), plus `manifest.json` and
`SCHEMA.md` as in every bundle, both recording
`treatment: outline`.

The outline lists `Pet`, `PetDetails`, `Tag`, and `PetStatus` with their fields. The manifest names the dropped types, including the planted waste type `AuditLog`, which nothing references. Treat the outline as a map of the part of the schema the task touches, not as a schema you can run.

## Standalone JSON Schema: parts-schema.json

`tests/fixtures/parts-schema.json` is a small standalone JSON Schema
(a workshop parts catalogue) with five definitions in `$defs`:
`Widget`, `Gadget`, `Sprocket`, plus two planted waste definitions,
`Doohickey` and `Thingamajig`, that slicing by `Widget` should drop.
`Gadget` also carries a remote `$ref` to
`https://example.com/schemas/materials.json#/definitions/Material`,
which is never fetched.

```bash
ghostschema inspect tests/fixtures/parts-schema.json
ghostschema slice tests/fixtures/parts-schema.json --select Widget -o /tmp/widget-bundle
```

The reduced `spec.json` keeps `Widget`, `Gadget`, and `Sprocket`
(reachable through `Widget`), drops `Doohickey` and `Thingamajig`
by name in the manifest, adds a root `$ref` pointing at the single
selected definition, and lists the remote materials reference as
unresolved. To keep the root document itself instead, select
`--select root`; to keep everything, use `--all`.
