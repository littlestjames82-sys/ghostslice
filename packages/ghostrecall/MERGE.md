# GhostRecall — merge report (Oct 18, 2026)

Merger redo, performed with real shell commands after the first attempt
was found to have applied nothing. Method: merged/ and pristine-check/
were both rebuilt fresh from pristine `~/workspace/ghostrecall/`
(rsync, excluding `__pycache__`/`.pytest_cache`). Multi-lane files were
combined with `git merge-file` three-way merges (base = pristine),
applying lanes in the order harden, then polish, then deepen.
Single-lane files were copied directly. Every merged multi-lane file
was grep-verified to contain each lane's signature changes; no harden
fix was dropped.

## Real test counts (observed in this redo)

- pristine-check: `24 passed in 27.71s` (`python3 -m pytest -q`, exit 0)
- merged: `68 passed in 29.58s` (`python3 -m pytest -q`, exit 0)
  = 24 baseline + 34 harden (`tests/test_harden.py`) + 10 deepen
  (`tests/test_contradictions.py`); polish added no tests.
- Acceptance: merged failures (none) are a subset of pristine-check
  failures (none). Zero failures unique to merged.
- `diff -rq merged pristine-check -x __pycache__ -x .pytest_cache`
  is NON-empty: 14 modified files + 3 new files (listed below).

## File provenance

### Harden only
- `tests/test_harden.py` — NEW, copied from harden.

### Polish only (copied from polish)
- `examples/README.md`
- `src/ghostrecall/__main__.py`
- `src/ghostrecall/dashboard.py`
- `src/ghostrecall/model.py`
- `src/ghostrecall/modes.py`
- `src/ghostrecall/tokens.py`

### Deepen only (copied from deepen)
- `src/ghostrecall/conflicts.py` — NEW.
- `tests/test_contradictions.py` — NEW.

### Multi-lane (three-way merged; all merges clean, see Conflicts)
- `src/ghostrecall/bundle.py` — harden + polish + deepen.
- `src/ghostrecall/cli.py` — harden + polish + deepen.
- `src/ghostrecall/recall.py` — harden + polish + deepen.
- `src/ghostrecall/mcp_server.py` — harden + polish.
- `src/ghostrecall/profile.py` — harden + polish.
- `src/ghostrecall/secrets.py` — harden + polish.
- `src/ghostrecall/sources.py` — harden + polish.
- `README.md` — polish + deepen.

### Not changed by any lane
- `src/ghostrecall/__init__.py` — the task brief listed it as
  multi-lane, but it is byte-identical in pristine and all three lanes
  (md5 491d7b22d11b6135a54dd6653b37ab12 everywhere). Nothing to merge.
- Everything else (LICENSE, PLAN.md, pyproject.toml, fixtures, etc.)
  is pristine, unchanged.

## Conflicts and resolutions

No textual conflicts occurred: every `git merge-file` invocation
returned rc=0 and no conflict markers remain anywhere in merged/.
The lanes touched disjoint regions (harden = logic, polish =
docstrings/CLI help, deepen = new contradiction hooks), which the
per-file checks below confirm. Overlaps handled, file by file:

- `bundle.py`: harden base (fit validation, `check_bundle`
  malformed-manifest guards, slice-bundle manifest validation),
  polish docstrings for `build_bundle`/`check_bundle` merged in,
  deepen `possible-contradiction` RECALL.md rendering merged in.
  Grep-verified: "fit must be a positive token budget",
  "manifest is not a JSON object", both polish docstrings, and the
  `possible-contradiction` branch all present.
- `cli.py`: harden base (`except (ValueError, OSError)` clean exit 2),
  polish help text/epilog/`RawDescriptionHelpFormatter` merged in,
  deepen `vs {c['other']}` conflict line merged in. All three
  grep-verified present.
- `recall.py`: harden base (blocked-before-pinning in `select()`,
  `max_items`/`recent_n` >= 1 validation), polish docstrings for
  `tfidf_rank`/`is_pinned`/`explain` merged in, deepen
  `from .conflicts import detect_contradictions` +
  `conflicts.extend(detect_contradictions(...))` merged in.
  All grep-verified present.
- `mcp_server.py`: harden blocked-item skip in `recall_search`
  ("defence in depth") + polish `_call`/`serve` docstrings. Both present.
- `profile.py`: harden full type/range validation (incl. bool rejected
  for `memory_budget_fraction`) + polish `load_profile` docstring. Both present.
- `secrets.py`: harden placeholder exemption scoped to the matched
  secret (`m.group(0)`) + polish `scan_text` docstring. Both present
  (see Suspicious note on the docstring wording).
- `sources.py`: harden project-relative IGNORE_DIRS matching,
  forbidden-root is/contains/inside refusal
  (`forb in root.parents or root in forb.parents`), non-current status
  words mapping to superseded, duplicate decision-id disambiguation
  (`seen_ids`) + polish `assert_project_root`/`collect_items`
  docstrings. All grep-verified present.
- `README.md`: polish base (install/quick-start, command table,
  profile docs) + deepen unlinked-contradiction documentation merged
  in. Grep-verified: `pip install -e .` and the
  `possible-contradiction` section both present.

## Suspicious / notes

- `secrets.py`: the polish docstring still says "Lines mentioning a
  placeholder word ... are exempt", which describes the OLD line-scoped
  behaviour. The harden code below it scopes the exemption to the
  matched secret only. Behaviour is harden's (correct and tested); only
  the docstring wording is imprecise. Left as the lanes wrote it and
  flagged here rather than silently edited.
- `build/lib/` in both trees is the stale pristine build artifact;
  no lane regenerated it and it was left untouched. Source of truth
  is `src/`.
- No IMPROVE.md was carried into merged/ (verified: none present
  before this MERGE.md was written).
- Pristine `~/workspace/ghostrecall/` was never edited; nothing was
  pushed to GitHub.
