# GhostDeps v0.1 - Fix report (REPORT_B.md findings F1 and F2)

Scope: `src/**` only (`src/ghostdeps/manifests.py`,
`src/ghostdeps/xref.py`). No tests were edited or weakened; no other
files were touched.

Full suite, before and after:

```
PYTHONPATH=src python3 -m pytest tests -q
before: 19 passed, 0 failed
after:  19 passed, 0 failed
```

## F1 - `[build-system]` requires counted as declared dependencies

**Root cause.** `_parse_pyproject` in `manifests.py` appended
`[build-system] requires` entries to `res.declarations` with kind
`build`, so build tooling (typically `setuptools`) entered the
declared set and landed in "Declared, no import found in scanned
code" for nearly every pyproject project. PLAN.md scopes pyproject
parsing to project dependencies, optional-dependencies, and
dependency-groups; build-system requires are outside that scope.

**Fix.**

- `SourceResult` gains a separate `build_requirements` list (also
  present in `record()`, so doctor `--json` and the manifest carry
  it per source).
- `_parse_pyproject` now records `[build-system] requires` there,
  never in `declarations`. Build requirements therefore cannot enter
  the declared/imported comparison, and an exact pin written only in
  build-system requires no longer produces a manifest pin either
  (pins derive from declarations).
- `xref.build_pack` aggregates them into a top-level
  `build_requirements` list in the pack (name, spec, source) plus a
  `counts.build_requirements` count. DEPS.md surfaces them in their
  own clearly labelled section, "Build requirements as recorded",
  which states they are build tooling, are not counted in the
  declared dependencies, and are not compared against imports. The
  Summary gains a matching line when any are present.
- Cargo `build-dependencies` are unchanged: PLAN.md explicitly puts
  them in scope for Cargo.toml, so they remain declarations.

**Evidence (examples/python_project).** Before: "Declared
dependencies: 4", `setuptools` listed under "Declared, no import
found in scanned code" (declared-not-imported count 2). After:
"Declared dependencies: 3", declared-not-imported is `colorama`
only, and `setuptools` appears solely in the Build requirements
section (`build_requirements: [{name: setuptools, spec: "",
source: pyproject.toml}]` in deps-manifest.json).

## F2 - Lockfile pins listed for every package; pack larger than the lockfile

**Root cause.** `_parse_package_lock` recorded a pin for every
top-level `node_modules/*` entry in a lockfileVersion 3 lockfile.
npm installs transitive packages flat at the top level, so most of
those pins are transitive, and each one became a full pin line in
DEPS.md and a full per-pin record in deps-manifest.json.

**Fix.**

- The lockfile parser now splits pins into direct and transitive
  using the lockfile's own root entry (`packages[""]`): a pin is
  direct when its name appears in the root entry's `dependencies`,
  `devDependencies`, `peerDependencies`, or `optionalDependencies`;
  every other top-level pin is transitive. Each pin record gains a
  `direct` flag, and the source note now reports the real counts
  ("3 direct pin(s), 40 transitive pin(s), 43 package entries
  total") instead of calling all of them "top-level". The legacy
  lockfileVersion 1 flat shape has no root entry to split against;
  its entries stay direct, as before (verified on a synthetic v1
  lockfile). Nested entries remain counted only, as before.
- The manifest stays complete: every pin is still recorded.
  `sections.pins` keeps full per-pin records for direct pins (and
  for exact pins written in manifests, which are direct by
  construction). Transitive pins are recorded compactly in a new
  `sections.transitive_pins`: one group per (source, via) with a
  `count` and a sorted `name=version` list. `counts.pins_recorded`
  still counts every pin (43 on the node example);
  `counts.pins_transitive_recorded` reports the transitive share.
- DEPS.md "Version pins as recorded" lists direct pins in full,
  then one compact line per lockfile for transitive pins (count
  plus the `name=version` list), with a short paragraph stating the
  split. The Limits section wording was updated to match.

**Size re-check (examples/node_project, raw lockfile 8,158 bytes).**

| File | Before | After |
| --- | ---: | ---: |
| DEPS.md | 5,713 | 4,129 |
| deps-manifest.json | 9,112 | 5,121 |
| Pack total | 14,825 | 9,250 |

Pack total reduced by 5,575 bytes (-38%), with all 43 pins still
recorded (3 direct in full, 40 transitive compact). Honest note:
the total is still slightly larger than this example's raw
lockfile (9,250 vs 8,158). This synthetic lockfile's entries are
unusually light (short placeholder integrity strings on the direct
entries); what remains in the pack is the fixed report content
(sources, the three gap sections, limits, notes, manifest
scaffolding), not pin payload - the combined pin payload across
both files dropped from roughly 9,900 to roughly 2,300 bytes. On
lockfiles whose entries carry their usual resolved/integrity
weight (the test fixture in `test_pack_node.py`, and real project
lockfiles) the pack is smaller than the raw lockfile, and the
suite's size test passes.

## Manifest schema changes (additive, one restructuring)

- Pin records gain `"direct": true/false`.
- New `sections.transitive_pins` (groups described above);
  `sections.pins` now holds direct pins only.
- New top-level `build_requirements`; each source record gains a
  `build_requirements` list.
- `counts` gains `pins_transitive_recorded` and
  `build_requirements`. All pre-existing keys are unchanged.

## Spot checks run

- Node example: direct pins express 4.18.2, lodash 4.17.21,
  typescript 5.4.5 in full; 40 transitive pins in one compact line
  and one compact manifest group; manifest pin total 43.
- Python example: declared 3, `setuptools` only in the build
  section (see F1 evidence).
- Synthetic lockfileVersion 1 project: packs normally, pins
  recorded as direct.
- Wording scan over both example packs: no banned verdict phrases
  ("safe to remove", "vulnerable", "outdated", "latest version",
  "dead code", "security risk", "critical severity").
- Doctor on the Python example still exits 1 (the planted numpy
  finding), unchanged.

## Gates held

Stdlib only, local only, no network, no push, no PyPI/publish, no
announcements, no spend. Evidence-only wording rules unchanged; the
core's banned-wording guard on DEPS.md still runs before writing.
