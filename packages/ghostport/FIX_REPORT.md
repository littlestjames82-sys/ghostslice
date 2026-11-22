# GhostPort - Fix Report (Agent B known-gap fixes, core)

Date: Oct 14, 2026. Scope: fix agent for GhostPort, parent-directed.
Owned for this fix: `src/**` and the python-upgrade pattern pack data
only. No tests were edited or weakened. Planner only (no codemods),
stdlib only, no network, no push, no publish, no spend.

## Baseline (before fix)

Run from `~/workspace/ghostport/`: `python3 -m unittest discover -s tests`

**24 tests, 22 pass, 2 fail**, both failures the deliberate known-gap
tests in `tests/test_pack_gaps.py` documented in `REPORT_B.md`:

- `test_distutils_from_import_form_is_hit` (PYUP005)
- `test_threading_isalive_is_hit` (PYUP007)

Baseline reproduced by this agent before editing.

## Fix 1 - PYUP005: import_module matcher now covers from-imports of submodules

File: `src/ghostport/scanner.py`, `_matches()`, `import_module` kind,
`ast.ImportFrom` branch.

Before, an `ImportFrom` hit only when the imported-from module equalled
a listed module exactly (`node.module in mods`), so the idiomatic
`from distutils.core import setup` (module `distutils.core`, listed
module `distutils`) produced no hit.

After: an `ImportFrom` also hits when the module is a submodule of a
listed module, mirroring the prefix rule the `ast.Import` branch already
used:

```python
if node.module in mods or any(node.module.startswith(m + ".") for m in mods):
    lines.append(node.lineno)
```

The `m + "."` form (not a bare string prefix) is what keeps look-alikes
safe: `from importlib import ...` does not hit PYUP004's listed `imp`
(`importlib` does not start with `imp.`), and `from typing import ...`
does not hit PYUP010's `typing.io` / `typing.re`.

Spot checks (outside the suite):

- `from distutils.core import setup` -> PYUP005 hit at line 1.
- Negative project (`from setuptools import setup`,
  `from importlib import import_module`, `import importlib.util`)
  -> 0 hits.

## Fix 2 - PYUP007: Thread.isAlive() added to the pattern

Files: `patterns/python-upgrade.json` and
`src/ghostport/packs/python-upgrade.json` (the two copies of the
python-upgrade pack data; kept byte-identical, `diff` clean after edit).

PYUP007's `attribute_or_name` matcher name list went from
`["currentThread", "activeCount", "isDaemon", "setDaemon"]` to
`["currentThread", "activeCount", "isDaemon", "setDaemon", "isAlive"]`.
`Thread.isAlive()` was removed in Python 3.10 in the same threading
camelCase cleanup the pattern already cites (reference date 2021-10-04,
Python 3.10 What's New), so no reference change was needed. Only
`isAlive` was added, no other aliases, per the directed fix.

Spot check: `t.isAlive()` -> PYUP007 hit; the look-alike `t.is_alive()`
plus `threading.current_thread()` -> 0 hits.

## GhostSlice check re-verification of a generated unit bundle

Generated fresh after the fixes (all output under `/tmp`, repo untouched):

1. Copied `examples/fixture/` to `/tmp/ghostport-fix-check/fixture`.
2. `PYTHONPATH=src python3 -m ghostport plan <fixture> --pack python-upgrade`
   (4 units, cycle unit combined as before).
3. `PYTHONPATH=src python3 -m ghostport bundle <fixture> --unit unit-src-pkg-mid -o /tmp/ghostport-fix-check/bundle-mid`
   (4 files: mid full, base signatures, top signatures, covering test full;
   129 sliced estimated tokens).
4. `PYTHONPATH=~/workspace/ghostslice/src python3 -m ghostslice check /tmp/ghostport-fix-check/bundle-mid`

Result, exactly as returned:

```json
{
  "ok": true,
  "errors": [],
  "files_checked": 4,
  "total_sliced_tokens": 129,
  "total_original_tokens": 200,
  "artifacts_checked": [],
  "redaction_checked": false
}
```

Exit code 0. This also settles the open note at the end of
`REPORT_B.md`: a GhostPort generated unit bundle does validate under
`ghostslice check` (ok: true, 0 errors), because `src/ghostport/tokens.py`
prefers GhostSlice's own estimator when the GhostSlice checkout is
reachable, as it was here.

## Final suite result (after fix)

Run from `~/workspace/ghostport/`: `python3 -m unittest discover -s tests`

**Ran 24 tests, OK - 24 pass, 0 fail.** (Baseline was 24 tests,
22 pass, 2 fail; the only change is the two known-gap tests now pass.
No test file was modified.)

## Files changed

- `src/ghostport/scanner.py` (ImportFrom prefix match for import_module)
- `patterns/python-upgrade.json` (PYUP007 adds `isAlive`)
- `src/ghostport/packs/python-upgrade.json` (same PYUP007 change, copies in sync)
- `FIX_REPORT.md` (this file, new)

No other files changed. Gates held: stdlib only, planner only,
no network, no push/publish/spend.
