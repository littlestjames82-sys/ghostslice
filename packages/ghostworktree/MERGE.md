# GhostWorktree — MERGE record (2026-10-18)

Merged tree: `~/workspace/.improve-2026-10-18/ghostworktree/merged/`
Built as a fresh copy of the pristine tree (`~/workspace/ghostworktree/`,
never edited, never pushed), with the three lane copies applied in the
order harden, then polish, then deepen. No `IMPROVE.md` is present in
this tree (lane bookkeeping only).

## Final test counts (all run in this session, `python3 -m pytest -q`)

| Tree | Result |
| --- | --- |
| harden lane | 53 passed (42 baseline + 11 in `tests/test_harden.py`) |
| polish lane | 42 passed (baseline, docs/help only) |
| deepen lane | 53 passed (42 baseline + 11 in `tests/test_doctor.py`) |
| **merged** | **64 passed, 0 failed** (42 baseline + 11 harden + 11 deepen) |

Merged passes the full union of all three lanes: at least what the
best lane passed, with zero new failures versus every lane.

## Files from a single lane (copied verbatim)

- From harden: `tests/test_harden.py` (new).
- From deepen: `tests/test_doctor.py` (new).
- From polish: `examples/README.md`, `src/ghostworktree/__init__.py`,
  `src/ghostworktree/__main__.py`, `src/ghostworktree/errors.py`.

## Files changed by multiple lanes (hand-merged, both/all changes kept)

- `src/ghostworktree/envcopy.py` (harden + polish): harden's symlink
  skip in `find_example`, `import os`, and `os.path.lexists` seeding
  checks, with polish's expanded docstrings on both functions (the
  `find_example` docstring also notes symlinked candidates are
  skipped).
- `src/ghostworktree/ports.py` (harden + polish): harden's bool/non-int
  requested-port rejection and malformed-range validation in
  `allocate`, with polish's docstrings on `parse_range` and `allocate`.
- `src/ghostworktree/registry.py` (harden + polish + deepen conflict,
  see below): harden's `locked()`/`save()` `OSError`-to-`RegistryError`
  wrapping and `load()` port/duplicate validation, with polish's
  docstrings on `default_root`, `registry_path`, `load`, `save`,
  `find`, `used_ports`. The `load` docstring was rewritten to describe
  the harden rules (invalid port includes bool/out-of-range; duplicate
  names rejected) instead of polish's older "non-integer port" wording.
- `src/ghostworktree/gitops.py` (all three): polish's docstrings on all
  helpers as the base; deepen's `worktree_list` docstring and its
  `locked`/`prunable` porcelain parsing added; harden's
  `branch_delete_safe` change (`git branch -d -- <branch>` plus its
  explanatory comment) added, with the polish docstring adjusted to
  read `git branch -d --` so docs match the hardened call.
- `src/ghostworktree/core.py` (all three): harden's code as the base
  (`_BRANCH_BAD_CHARS`, `validate_branch`/`validate_base`, rewritten
  destination containment, reuse of the single `worktree_list` call);
  polish's docstrings added to `validate_name`, `create`,
  `list_worktrees`, `status_one`, `status`, `cleanup` (the
  `validate_name` docstring was extended with one sentence covering
  harden's extra `..`/trailing-`.`/`.lock` rejections); deepen's
  `doctor()` inserted verbatim between `status_one` and `status`,
  except for its registry load call (see conflict below).
- `src/ghostworktree/cli.py` (all three): polish's CLI as the base
  (expanded module docstring, `_NAME_HELP`, per-command
  descriptions/epilogs and help text); the first docstring line updated
  to deepen's `create / list / status / doctor / cleanup`; harden's
  `_p_list` `.get()` fix (with its comment) applied; deepen's
  `_p_doctor` printer copied verbatim and a `doctor` subparser added
  between `status` and `cleanup` using deepen's help text verbatim
  plus a polish-style long `description`; polish's top-level epilog
  gained one line, `ghostworktree doctor ~/repo`. Verified: top-level
  `--help` lists all five commands and `doctor --help` renders.
- `README.md` (polish + deepen): polish's README as the base (Quick
  start, exit-code table, Common refusals); deepen's `doctor` line
  added to the Commands block and deepen's "The doctor audit" section
  inserted verbatim immediately before "Safety rules in v0.1" (the
  position it occupies relative to surrounding sections in the deepen
  README).

## Conflicts and how they were resolved

1. **REAL BEHAVIOR CONFLICT — registry duplicate names: harden vs
   deepen `doctor` (resolved, no harden fix dropped).**
   Harden makes `registry.load()` raise `RegistryError` on duplicate
   worktree names (pinned by `test_registry_rejects_duplicate_names`).
   Deepen's `doctor` was designed against a registry that tolerates
   duplicates and expects to *report* `duplicate_name`/`duplicate_port`
   as problems with exit 1 and a JSON report (pinned by
   `test_doctor_reports_duplicate_port_and_name`). A naive merge in
   either direction fails one lane's test: strict load makes doctor
   die with a named error instead of reporting; tolerant load drops
   the harden fix.
   Resolution (combined behavior): `load()` keeps the strict harden
   default for every caller, and gains a keyword-only escape hatch,
   `load(root, *, allow_duplicate_names=False)`. Only `core.doctor()`
   passes `allow_duplicate_names=True` (with an explanatory comment),
   so doctor can load a duplicate-carrying registry and report the
   duplicates itself. Duplicate *ports* were never rejected by harden,
   so that half of doctor's check needed no change. Both pinning tests
   pass in the merged suite. Note for reviewers: this is the one place
   where merged code is not byte-identical to any single lane; the
   deviation is two lines in `registry.py` (signature + one condition),
   one call site in `core.py`, and the documenting docstring.
2. **`cli.py` module docstring (polish vs deepen, same line):** polish
   expanded the one-liner into a paragraph still titled
   "create / list / status / cleanup"; deepen changed only the title
   to include `doctor`. Merged keeps polish's paragraph with deepen's
   title. No behavior involved.
3. **`gitops.branch_delete_safe` docstring vs call (polish vs
   harden, same function):** different regions (docstring vs call
   arguments), merged mechanically; docstring wording adjusted from
   `git branch -d` to `git branch -d --` for accuracy (see above).
4. **`core.validate_name` docstring vs body (polish vs harden):**
   polish documented the pristine body; harden extended the body.
   Merged keeps both, docstring extended by one sentence (see above).
   Polish's `create`/`cleanup` docstrings describe defaults and the
   dirty rule only and remain accurate against harden's code.

No other same-region code conflicts existed: in every other shared
file the lanes touched disjoint regions (harden = logic, polish =
docstrings/help, deepen = new `doctor` function/parser/README section).

## Anything suspicious

- Nothing else suspicious found. All harden fixes verified present by
  marker check after the merge (env symlink skip + `lexists`, port
  type/range validation, branch/base validation, containment rewrite,
  `.get()` listing, `--` in safe branch delete, registry error
  wrapping), and the merged suite passes harden's 11 regression tests
  unchanged.
- Residual known from harden's own notes, unchanged by this merge: a
  hardlink from `.env.example` to `.env` shares an inode and is not
  detected; doctor flags hand-made unregistered worktrees by design
  (exit 1 is the signal, not noise).
- The pristine tree was not modified and nothing was pushed anywhere.
