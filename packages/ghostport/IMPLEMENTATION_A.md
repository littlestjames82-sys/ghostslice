# GhostPort v0.1 - Agent A (core builder) implementation record
Date: 2026-10-14. Scope per PLAN.md: ONE pack, planner + sequencer, stdlib only.
Agent A owned: `src/**`, `pyproject.toml`, `patterns/**`, this file. Tests/README/examples are Agent B's; the fixture under `examples/fixture/` was added by Agent A solely as a smoke target (Agent B's `examples/demo_project/` was also scanned, read-only).

## What was built
- `pyproject.toml`: setuptools, `ghostport` console script, zero dependencies, Python >= 3.10.
- `src/ghostport/patterns.py`: pack format + loader. Validation refuses any pattern missing id, description, reference, reference_date, or reference_url, refuses duplicate ids, unknown matcher kinds, and undated packs. ("An undated pattern is a bug" is enforced, not just documented.)
- `patterns/python-upgrade.json` (also shipped as package data at `src/ghostport/packs/python-upgrade.json`): the ONE first pack, **python-upgrade v1.0.0, dated 2026-10-14**, 12 patterns PYUP001-PYUP012. Every pattern carries a plain-words description, a Python What's New / PEP reference, its release date, and a docs URL. Matcher kinds: `import_module`, `import_from`, `attribute`, `attribute_or_name` (AST-driven, data-only).
- `src/ghostport/scanner.py`: static AST scan (files parsed, never imported or executed). Output: hits (file, line, pattern id, description), files with zero hits (honest negative), parse errors, and languages present but NOT covered by the pack, named. Report language says zero hits means no hits *for this pack version only*, never "ready to upgrade".
- `src/ghostport/graph.py`: project import graph, unit formation (one unit per hit file), SCC (Tarjan) cycle detection that combines cycle members into one unit named as a blocker, leaves-first topological sequencing (a unit always after touched units it imports), covering-test detection by import graph with method labelled, and profile overrides (`port.merge` combines units; `port.pin_first`/`port.order` are tie-breakers only and never override dependency order). `src/` layout prefix is normalised for module resolution.
- `src/ghostport/planning.py`: `build_plan` + `PORT_PLAN.md` / `port-plan.json` writers (unit table in order, per-unit estimated tokens, total, blockers, not-covered languages, zero-hit files).
- `src/ghostport/bundle.py`: per-unit bundle in GhostSlice bundle shape: unit files full, dependency and caller units as extractive AST signatures, covering tests full, `manifest.json` (path/mode/original/sliced token counts/sha256/totals), `PROMPT.md`, and `UNIT.md` checklist (patterns with locations, contract notes for not-yet-ported callers and already-sequenced dependencies, cycle note, test command from profile - recorded, never run by GhostPort - and the state box).
- `src/ghostport/tokens.py`: prefers GhostSlice's own estimator when a GhostSlice checkout/install is reachable, so bundles validate under `ghostslice check` (verified below); falls back to a documented chars/4 estimate. All figures labelled estimates.
- `src/ghostport/ledger.py`: `<project>/.ghostport-history.jsonl`. States: planned, bundled, ported-claimed (labelled a claim), verified. **Hard rule implemented in code, not copy:** `record_state(..., "verified")` raises; there is no CLI flag for it. The only path is `record_verified()`, which parses a GhostVerify post report (JSON with `ok: true` or a passing `verdict`, plus passing check) and stores the report path + its sha256.
- `src/ghostport/status.py`: plan + ledger resumption view (per-unit state, verified count, estimated tokens remaining, next unit).
- `src/ghostport/profile.py`: reads the `port` section of `.ghostslice.json`; unknown keys fail loudly.
- `src/ghostport/cli.py` + `__main__.py`: commands `scan`, `plan`, `bundle`, `claim`, `verify`, `status`, `packs`. Exit 2 on pack/profile/value errors.

## Hard rules kept
- Planner only: no codemods, no auto-fixes, no rewriting anywhere. No command modifies project source; writes are the plan files, bundle output, and the ledger.
- GhostPort never runs tests: test commands are recorded in UNIT.md for GhostVerify post.
- No network, no dependencies, no push/publish/spend.

## Smoke record (all run 2026-10-14, Python 3.12.3, `PYTHONPATH=src python3 -m ghostport ...`)
Fixture: `examples/fixture/` (base -> mid -> top chain, cyc_a <-> cyc_b cycle, clean.py negative, tests/test_mid.py cover), copied to /tmp for runs so no ledger/plan files land in the repo example.

1. **scan on fixture: 8 hits in 5 files, 3 Python files with zero hits.** Hand-checked, all correct:
   - base.py:2 PYUP004 (`import imp`), base.py:3 PYUP005 (`from distutils import core`)
   - mid.py:2 PYUP001 (`from collections import Mapping`), mid.py:10 PYUP012 (`datetime.utcnow()`)
   - top.py:9 PYUP006 (`configparser.SafeConfigParser()`), top.py:10 PYUP009 (`ssl.wrap_socket`)
   - cyc_a.py:8 PYUP003 (`inspect.getargspec`), cyc_b.py:8 PYUP011 (`locale.getdefaultlocale`)
   - clean.py (collections.abc, `datetime.now(timezone.utc)`): **zero hits, as required.**
2. **plan on fixture:** order was cycle-combined unit first (no touched deps), then base, then mid, then top. Dependency order correct (base before mid before top). The cyc_a/cyc_b cycle was combined into `unit-cycle-src-pkg-cyc-a-src-pkg-cyc-b` and listed under Blockers in PORT_PLAN.md. Covering test `tests/test_mid.py` correctly attached to the mid unit. Total estimated tokens (GhostSlice estimator): 255 across 4 units.
3. **bundle for mid unit:** 4 files (mid full, base signatures, top signatures, test full), manifest sha256 recorded in the ledger. **`ghostslice check` on the bundle: ok: true, 0 errors, 4 files checked** (run with PYTHONPATH pointing at the GhostSlice checkout).
4. **State integrity:** status on a fresh plan shows **verified units: 0**. `claim` recorded a ported-claimed *claim*. `verify` with a non-passing report (`{"ok": false}`) was refused with exit 2 ("does not record a passing verdict"), nothing written. `verify` with a passing GhostVerify-shaped report succeeded and status then showed the mid unit verified, tokens remaining dropping accordingly. A direct `record_state(..., "verified")` call was confirmed to raise ValueError.
5. **Second scan target (Agent B's example, read-only):** `examples/demo_project` scanned to 3 hits, spot-checked: `legacy/plugin_loader.py:2` is `import imp` (PYUP004, correct).
6. **Real-repo scans (Ryan's own, read-only):** GhostSlice repo: 75 Python files scanned, **0 hits**. Ghost Hands: 59 files, **0 hits**. Agent Seatbelt tree: 0 hits. Consistent with modern codebases; zero is reported as pack-specific, not as upgrade-readiness. (A full first-20-hit hand-check against a legacy real repo was not possible: no in-workspace real repo produced hits. The 8 fixture hits + 3 demo hits above were each hand-verified against the source line.)

## Known limits (honest)
- Attribute/name matching is syntactic: a local variable or method that happens to share a flagged name (for example a user-defined `readfp`) can false-positive in PYUP006-class patterns; the report gives file+line so a human can judge. Pattern fixtures with explicit negatives are Agent B's test scope.
- Import resolution is best-effort static: dynamic imports and string dispatch are invisible, so sequencing can be wrong around them; the profile merge/pin overrides exist for that case.
- Pack coverage is Python only; other languages are reported as not covered, never scanned-and-passed.
- GhostSlice estimator preference depends on a reachable GhostSlice checkout/install; without one, bundle token counts use the fallback estimator and `ghostslice check` would flag token mismatches (hash validation is unaffected).
