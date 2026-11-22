# GhostPort
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostport/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostport/actions/workflows/ci.yml/actions)

**Port a codebase one proven slice at a time.**

Version and framework migrations fail in a predictable way: the surface
that actually needs changing is a small fraction of the repo, but an
agent (or a person) handed the whole repo makes unrelated edits, and a
single file handed over alone loses the call graph, so a migrated callee
breaks an unmigrated caller at run time.

GhostPort is the migration slicer and workbench paired with
[GhostSlice](https://github.com/littlestjames82-sys/ghostslice). It
scans a project for migration patterns, groups the hits into units,
orders the units leaves-first over the dependency graph, and exports one
GhostSlice bundle per unit: the unit in full, already-ported
dependencies as stable context, not-yet-ported callers as signatures,
and a checklist tied to the unit's tests.

By Ghost Developer Studio. MIT licensed (see `LICENSE`). **Zero dependencies**
(Python standard library only), **local-first**: no network calls, no
telemetry, your code never leaves the machine.

Position in the Ghost stack: GhostSlice builds task bundles,
GhostPort builds *migration* bundles from pattern state,
GhostVerify checks each ported unit when it comes back.

> Status: v0.1.0, as in `pyproject.toml`. This README describes the
> v0.1 scope in `PLAN.md`: one pack (`python-upgrade`), seven commands
> (`scan`, `plan`, `bundle`, `claim`, `verify`, `status`, `packs`), and
> the local ledger. The test suite under `tests/` runs against this
> tree; see Tests below.

## What GhostPort does not do

- It **never performs the migration**: no code rewriting, no auto-fixes,
  no codemods. Port prepares and sequences; agents and humans port.
- It does **not run your tests**. That is GhostVerify's post step, in a
  temporary copy, with its own guardrails.
- A scan with no hits says **"no hits for pack X version Y"**, never
  "this project is ready to upgrade". A pattern pack only finds what
  its patterns know, and the scan names the languages it does not cover.

## Install

From a checkout of this repo:

```bash
pip install .
ghostport --help
```

Requires Python 3.11 or newer. No packages are installed besides
GhostPort itself: the runtime is the Python standard library only.

Without installing, run it from the checkout instead (this is also how
the test suite drives it):

```bash
PYTHONPATH=src python3 -m ghostport --help
```

Every command has its own help, for example
`ghostport scan --help` or `ghostport bundle --help`.

## Quickstart

```bash
ghostport scan  ~/my-project --pack python-upgrade
ghostport plan  ~/my-project --pack python-upgrade
ghostport bundle ~/my-project --unit unit-legacy-storage -o /tmp/port-unit-001
ghostport claim  ~/my-project --unit unit-legacy-storage --by ryan
ghostport verify ~/my-project --unit unit-legacy-storage --report /path/to/ghostverify-report.json
ghostport status ~/my-project
ghostport packs  --pack python-upgrade
```

`--pack` defaults to `python-upgrade` everywhere it appears, so the
short forms (`ghostport scan ~/my-project`) do the same thing. `scan`,
`plan`, and `status` also accept `--json` for a machine-readable view.
Exit code is 0 on success and 2 on a usage, pack, or profile error.

1. **scan** lists every pattern hit (file, line, pattern id, plain-words
   description), the files scanned with zero hits, and the languages in
   the project the pack does not cover. It also prints the pack version
   and date, so a stale pack looks stale. Scan writes nothing.
2. **plan** writes `PORT_PLAN.md` and `port-plan.json` (into the project
   directory, or `--out DIR`): units in dependency order (leaves
   first), covering tests attached where known (method labelled),
   per-unit estimated token totals, and blockers. A cycle in the touched
   set is combined into one unit and named, never silently ordered.
   Plan also records a `planned` entry per unit in the ledger.
3. **bundle** exports one unit as a bundle folder (`manifest.json`,
   `PROMPT.md`, `files/`, and `UNIT.md`): the unit and its covering
   tests in full, related dependency and caller units as signatures,
   patterns to fix with locations, contract notes (callers included at
   signatures that must keep working), the test command from the
   profile if any, and a state box. Without `-o`, the bundle goes to
   `<project>/.ghostport/bundles/<unit>`. The bundle validates with
   `ghostslice check`.
4. **claim** records in the ledger that someone says a unit is ported:
   `ported-claimed`, with `--by` naming who. A claim is not proof.
5. **verify** records a unit as `verified`, and is the only way to do
   so: `--report` must point at a GhostVerify post report, which is
   validated and hashed into the ledger. There is no flag to set
   verified by hand.
6. **status** is the resumption view for a migration that spans weeks:
   units planned / bundled / ported-claimed / verified, estimated tokens
   remaining, and the next unit in order.
7. **packs** shows where a pack is searched for and, with `--pack`,
   lists its patterns with their dated source references.

Try it on the bundled demo (read-only: this scan changes nothing):

```bash
ghostport scan examples/demo_project --pack python-upgrade
# 3 hits: PYUP004 in legacy/plugin_loader.py, PYUP003 in legacy/report.py,
#         PYUP006 in legacy/storage.py
```

## The first pack: `python-upgrade`

One pack, done well, beats five packs done badly. The first pack is a
Python version-upgrade pattern set. Every pattern carries an id, a
plain-words description, and a dated source reference; an undated
pattern is a bug.

The pack as shipped in `patterns/python-upgrade.json` (v1.0.0,
2026-10-14) has twelve patterns, ids `PYUP001` to `PYUP012`:

| ID | Pattern |
|---|---|
| PYUP001 | ABCs imported from `collections` instead of `collections.abc` (removed 3.10) |
| PYUP002 | `asyncio.coroutine` decorator (removed 3.11) |
| PYUP003 | `inspect.getargspec` (removed 3.11) |
| PYUP004 | `imp` module (removed 3.12) |
| PYUP005 | `distutils` (removed 3.12, PEP 632) |
| PYUP006 | `configparser.SafeConfigParser` / `readfp` (removed 3.12) |
| PYUP007 | `threading` camelCase aliases (`currentThread`, `activeCount`, ...) |
| PYUP008 | `unittest` legacy aliases (`failUnless`, `assertEquals`, ...) (removed 3.12) |
| PYUP009 | `ssl.wrap_socket` / `ssl.match_hostname` (removed 3.12) |
| PYUP010 | `typing.io` / `typing.re` pseudo-modules (removed 3.12) |
| PYUP011 | `locale.getdefaultlocale` (deprecated 3.11, scheduled for removal) |
| PYUP012 | `datetime.utcnow` / `utcfromtimestamp` (deprecated 3.12) |

Pattern hits are findings only: file + line + pattern id, in the same
redaction-safe style as GhostSlice's secrets guard.

Two gaps found against the first cut of this pack are fixed, and the
tests that exposed them now pass as regression tests in
`tests/test_pack_gaps.py` (history in `REPORT_B.md` and
`FIX_REPORT.md`): the idiomatic `from distutils.core import setup` form
is hit by PYUP005, and `Thread.isAlive()` is in PYUP007's name list.
`fractions.gcd` (removed 3.9) is a proposed thirteenth pattern, with a
fixture pair in the test suite, but is **not** in pack v1.0.0.

## State, the ledger, and the word "verified"

Progress lives in one local file in the project,
`.ghostport-history.jsonl`. Each entry records a unit, its bundle hash,
a state change (`planned`, `bundled`, `ported-claimed`, `verified`),
and, for verified units, the GhostVerify report it rests on.

**Verified is not a claim.** `ported-claimed` is a user or agent saying
the work is done. `verified` can only be written from a GhostVerify post
report referenced in the ledger. A project whose ledger has claims but
no Verify report shows **zero verified units** in `status`, which is
the correct answer.

## Profile

GhostPort reads a `port` section in the project's `.ghostslice.json`:

```json
{
  "port": {
    "pack": "python-upgrade",
    "budget_tokens": 20000,
    "test_command": null,
    "merge": [],
    "pin_first": [],
    "order": []
  }
}
```

All keys are optional. The supported keys are exactly: `pack`,
`budget_tokens` (per-unit budget), `test_command` (recorded in
`UNIT.md`; GhostPort never runs it), `merge` (a list of lists of unit
ids or files to combine into one unit), `pin_first` and `order`
(tie-breakers only: they choose among units whose dependencies are
already satisfied, and never override dependency order), and
`pattern_overrides` (accepted by the loader; it has no other effect in
v0.1). An unknown key fails loudly with a ProfileError
instead of being silently ignored, so a misspelt key is caught at plan
time. Copy-ready version: `examples/ghostslice-profile-snippet.json`.

Static graphs miss dynamic calls (registries, string dispatch), so the
profile supports a manual merge/reorder for exactly that case. When an
override is used, the plan says so.

Token totals are **estimates**, labelled as estimates everywhere and
never presented as live prices or billed amounts. The estimator is
GhostSlice's when a GhostSlice checkout or install is reachable (so a
bundle's figures agree with `ghostslice check`), and otherwise a
documented fallback of `ceil(len(text) / 4)`; the plan and every bundle
manifest name the method used in their `token_method` field.

## Examples

`examples/demo_project/` is a three-file legacy project with one hit
per file and a real dependency chain; `examples/sample_port_plan/`
holds labelled sample outputs; `examples/fixture/` is a larger sample
project (ordering chain plus a two-node cycle) of the kind the tests
use. See `examples/README.md` for the walkthrough.

## Tests

Run from the repo root:

```bash
python3 -m unittest discover -s tests
```

A green run ends with `OK`. The suite is stdlib `unittest` only; do
not substitute pytest, the suite is not written for it. Layer 1
validates the fixtures themselves (a positive and a look-alike
negative file per pattern, an ordering chain, a two-node cycle, a
resume ledger whose verified count must be zero). Layer 2 drives the
real CLI (`scan` / `plan` / `bundle` / `status`) against copies of
those fixtures, and asserts that scan and bundle leave the source
project byte-identical.

## Layout

```
src/ghostport/   core: scanner/pattern engine, unit formation, graph
                 sequencing, bundle export, ledger, CLI; a bundled copy
                 of the pack lives in src/ghostport/packs/
patterns/        pattern packs as data files (id, description, dated
                 reference per pattern)
tests/           unittest suite + fixtures
examples/        demo project, sample plan outputs, profile snippet
PLAN.md          the v0.1 plan this README follows
LICENSE          MIT licence
```

## Licence

MIT (see `LICENSE`), same pattern as GhostSlice, Agent Seatbelt, and
Ghost Hands. No paid layer is decided; additional maintained pattern
packs are the only paid candidate named in the plan, and nothing is
priced.

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
