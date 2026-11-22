# GhostSchema
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostschema/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostschema/actions/workflows/ci.yml/actions)

GhostSchema cuts a large API specification down to the part your task actually touches.

A real OpenAPI document can run to tens of thousands of tokens: hundreds of operations and component schemas, most of them irrelevant to the change you are making. Feeding all of it to a coding agent wastes budget and buries the endpoint that matters. GhostSchema follows the spec's own reference graph (`$ref` links) from the operations or schemas you select, keeps everything reachable, drops everything else, and writes a smaller spec plus a manifest that proves what was kept, what was dropped, and what could not be resolved.

It is a GhostSlice companion. GhostSlice governs what an agent reads from a codebase; GhostSchema governs what it reads from an API contract. It runs entirely on your machine, with no network access and no dependencies beyond the Python standard library.

## Install

Requires Python 3.9 or newer. There are no third-party dependencies.

```bash
# From a checkout of this repository:
pip install .

# Then check it runs:
ghostschema --version
ghostschema --help
```

Without installing, run it as a module from the checkout:

```bash
PYTHONPATH=src python3 -m ghostschema --help
```

Every example below uses the installed `ghostschema` command; the
`python3 -m ghostschema` form takes the same arguments.

## What it handles

- **OpenAPI 3.x in JSON**: reduced to a valid smaller OpenAPI document by reachability.
- **Standalone JSON Schema in JSON**: reduced the same way, with unreachable `$defs` pruned.
- **GraphQL SDL** (`.graphql`, `.gql`, or SDL-looking text): outline only. See below.
- **YAML specs: refused.** The Python standard library has no YAML parser, and GhostSchema does not fake one. A `.yaml` or `.yml` file, or YAML content saved under a `.json` name, is refused with a clear message and exit code 2. Convert the spec to JSON first with a tool you trust, then slice the JSON.
- **Swagger / OpenAPI 2.0: refused**, with a message pointing you at converting to OpenAPI 3.x first. The reference layout differs and v0.1 does not guess at it.

## Quick start

```bash
# See what a spec is and what it contains
ghostschema inspect api.json

# Same listing as machine-readable JSON
ghostschema inspect api.json --json

# Keep one operation and everything it reaches
ghostschema slice api.json --select getPet -o bundle/

# Or pick by task wording (lexical matching, see Limits)
ghostschema slice api.json --task "add a pet to the store" -o bundle/

# Keep the whole document (baseline for token comparison)
ghostschema slice api.json --all -o bundle/
```

Standalone JSON Schema works the same way. Select a definition by
name, by pointer, or select the root document itself:

```bash
ghostschema inspect parts.json
ghostschema slice parts.json --select Widget -o bundle/
ghostschema slice parts.json --select '#/$defs/Widget' -o bundle/
ghostschema slice parts.json --select root -o bundle/
```

GraphQL SDL also uses the same two commands; `--select` takes exact
type names and the result is an outline bundle (see below):

```bash
ghostschema inspect schema.graphql
ghostschema slice schema.graphql --select Pet -o outline-bundle/
```

Worked examples with expected kept and dropped names are in
`examples/` (see `examples/README.md`).

## Choosing how to select

Give one selection mode per `slice` run. If more than one is given,
`--all` wins first, then `--select`, then `--task`:

| Mode | Flag | Use it when | How it picks |
| --- | --- | --- | --- |
| Select | `--select <ids>` | You know the exact ids. This is the precise route. | Only the named operations, schemas, definitions, or SDL types, plus everything reachable from them. |
| Task | `--task "<wording>"` | You have a task description but no ids yet. | Word matching over names, paths, summaries, tags, and property names. Anything scoring above zero is kept. See Limits. |
| All | `--all` | You want a baseline for token comparison, or no reduction. | Everything in the document. |

`--select` accepts a comma-separated list. For OpenAPI and JSON
Schema it accepts operationIds, `METHOD /path` pairs, bare paths,
schema or definition names, and JSON pointers such as
`#/components/schemas/Pet` or `#/$defs/Order`. For JSON Schema,
`root` (also `#` or `$root`) selects the root document. For GraphQL
SDL it accepts exact type names only. An unknown id fails loudly by
name with exit code 2; nothing is silently ignored.

If a `slice` run gets no `--task`, `--select`, or `--all`, it fails
with exit code 2 instead of guessing a selection.

## The bundle

Slicing writes a bundle directory (default `./schema-slice`, set with
`-o` / `--out`). The input file is never modified.

Every bundle contains:

- `manifest.json`: the audit record. Source path, sha256, and byte size; the format detected; the treatment (`reduced` or `outline`); the token estimator method used; estimated tokens before and after; your selection echoed back; kept lists; dropped lists; unresolved remote references with the pointers that referenced them; warnings.
- `SCHEMA.md`: the same record in plain words, for a human skimming the bundle.

A JSON bundle (OpenAPI or JSON Schema) also contains:

- `spec.json`: the reduced spec. It parses as the same kind of document you started with, and every local `$ref` inside it resolves inside it. GhostSchema checks this itself before writing; a closure failure is reported as an error, never shipped quietly.

An SDL bundle contains `outline.json` and `OUTLINE.md` instead of
`spec.json`. See the GraphQL section below.

On success `slice` prints a short summary to stdout: the format and
treatment, the estimated token change, how many items were kept and
dropped in each group, any unresolved references, any warnings, and
where the bundle was written.

## Exit codes

- `0`: success. `inspect` printed its listing, or `slice` wrote the bundle.
- `2`: the spec could not be processed and no bundle was written.
  This covers a missing file, unparseable input, a refused format
  (YAML or Swagger / OpenAPI 2.0), an unknown `--select` id, a
  selection that matched nothing, a `--task` with no usable terms,
  and an internal closure check failure on the reduced output.
  The reason is printed to stderr, prefixed with `ghostschema:`.

## Remote references are never fetched

A `$ref` that points at an http(s) URL, a file path, or anything that does not start with `#/` is **never fetched or resolved**. There is no network code path in v0.1. Remote refs are left in place in the reduced spec so nothing dangles silently, and each one is recorded in the manifest as unresolved, with the place it was referenced from. If your reduced spec lists unresolved refs, the agent reading it knows the picture has holes, and where they are.

Reachability also follows OpenAPI references that are not `$ref` keys: `discriminator.mapping` targets (a local pointer, a bare schema-name shorthand, or an external URI) and Link Object `operationId` / `operationRef` values, transitively. Keeping a polymorphic schema keeps the subtypes its mapping names; keeping a response keeps the operations its links name. External implicit targets follow the same rule as remote `$ref`s: never fetched, left in place, and recorded in the manifest as unresolved with a `via` naming the construct (`discriminator.mapping`, `link.operationId`, `link.operationRef`) that referenced them.

## GraphQL SDL: outline only, on purpose

SDL reachability by name cannot prove that a cut-down SDL document is still a valid, complete schema, so GhostSchema never emits one. For SDL input the bundle contains:

- `outline.json` and `OUTLINE.md`: the types reachable from your selection, with their fields, types, enum values, and union members.
- `manifest.json` (with `treatment: outline`, and dropped type names listed) and `SCHEMA.md`, as in every bundle.

Every artifact is labelled outline in its content. Treat an outline as a map of the part of the schema your task touches, not as a schema you can run.

## Limits, stated plainly

- **A reduced spec is a reading aid, not a deployable contract.** Do not ship `spec.json` as your API's source of truth. Slice a copy for the agent; keep the original as the contract.
- **Task selection is word matching.** `--task` scores operations and schemas by shared words in names, paths, summaries, tags, and property names. It will miss an operation whose wording shares nothing with your task. `--select` is the precise route; use it when you know the ids.
- **Token numbers are estimates.** Counts come from GhostSlice's calibrated estimator when a GhostSlice install or checkout is reachable, and from a documented characters-per-4 fallback otherwise. The manifest stamps which method produced the numbers.
- **Closure is proved, correctness is not.** GhostSchema guarantees every local `$ref` in the reduced output resolves inside that output. It does not validate your spec against the OpenAPI or JSON Schema meta-schemas, before or after slicing.
- **SDL parsing is outline-grade.** It is static pattern matching, not a full GraphQL grammar. Unusual descriptions, directives, or extension blocks may parse imperfectly; the outline lists what it found and the manifest warns about the grade.
- **Local files only.** One spec file in, one bundle directory out. No accounts, no telemetry, nothing leaves the machine.

## MCP

`ghostschema mcp` runs a stdio MCP server for MCP clients. Point the
client at the `ghostschema mcp` command; the server speaks JSON-RPC
over stdin and stdout and serves two tools:

| Tool | Arguments | Returns |
| --- | --- | --- |
| `schema_inspect` | `spec` (required) | The same listing as `inspect`: format, operations or definitions or types, source hash and size. |
| `schema_slice` | `spec` and `out` (required); `task`, `select` (a list of ids), and `all` (optional) | A capped manifest summary: format, treatment, token estimates, kept and dropped lists, unresolved references, and warnings. |

Payloads are summaries only, with no spec bodies by default, the
same discipline as GhostSlice's MCP server. In `schema_slice`
results, each kept, dropped, and unresolved list is capped at 200
entries, with a note saying how many more there were.

## Examples

See `examples/` for a mid-size fixture OpenAPI document and a GraphQL SDL sample, with a walkthrough of slicing each one, the exact commands to run, and the kept and dropped names to expect in each bundle.

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
