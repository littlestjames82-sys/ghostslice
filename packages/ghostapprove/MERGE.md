# GhostApprove — merge of harden / polish / deepen lanes (2026-10-18)

Tool: **ghostapprove**
Merged tree: `~/workspace/.improve-2026-10-18/ghostapprove/merged/`
Pristine tree `~/workspace/ghostapprove/` was never edited; nothing was pushed to GitHub.
No lane `IMPROVE.md` is present in the merged tree.

Method: fresh copy of pristine (skipping `__pycache__` / `.pytest_cache`), then
three-way merges (`git merge-file`, base = pristine) in lane order
harden → polish → deepen, file by file, with hand resolution where the
three-way merge conflicted or where two lanes touched the same region
in different forms. After assembly, a diff audit checked that no
lane-unique line was lost: every line removed relative to a lane is a
pristine line superseded by another lane (re-indented under harden's
`try:` wrappers, or pristine help/doc text replaced by polish's
expanded version), never a lane fix.

## Test counts (explicit comparison)

| Tree | Count | Source |
|---|---|---|
| Baseline (pristine) | 42 passed | each lane's IMPROVE.md |
| harden lane | 48 passed (42 + 6 new in `tests/test_harden.py`) | harden IMPROVE.md |
| polish lane | 42 passed (no new tests) | polish IMPROVE.md |
| deepen lane | 56 passed (42 + 14 new in `tests/test_verify.py`) | deepen IMPROVE.md |
| **merged** | **62 passed in 84.16s, exit 0** (`python3 -m pytest -q`) | run in this merged tree |

62 = 42 baseline + 6 harden + 14 deepen, exactly. Merged passes more
than the best single lane (deepen, 56) with **zero new failures versus
every lane**. Sanity subset run before the full suite:
`test_harden.py + test_verify.py + test_no_execution.py` = 24 passed.

## Files by lane

Copied verbatim from a single lane (no other lane touched them):

- polish: `src/ghostapprove/__init__.py`, `src/ghostapprove/__main__.py`,
  `examples/README.md`, `examples/WALKTHROUGH.md`
- harden: `tests/test_harden.py` (new file)
- deepen: `tests/test_verify.py` (new file)

Hand-merged (multiple lanes):

- `src/ghostapprove/model.py` — harden + polish
- `src/ghostapprove/store.py` — harden + polish + deepen
- `src/ghostapprove/cli.py` — harden + polish + deepen
- `README.md` — polish + deepen

All other files are byte-identical to pristine in every lane and in merged.

## Conflicts and how they were resolved

1. **`store.py` — `Store._ensure` (real conflict, harden vs polish).**
   Harden wrapped the `mkdir` in `try/except OSError → StoreError`;
   polish added a docstring and kept the bare `mkdir`.
   Resolution: polish docstring **plus** harden's try/except body.
   No harden fix dropped.

2. **`store.py` — all other shared regions (no textual conflict).**
   Polish's changes are docstrings only (`Store`, `read_ledger`,
   `load_record`, `status_of`, `list_requests`, `get_entry`, `ingest`,
   `decide`, `history`, `default_store_path`); harden's are logic in the
   same functions (ledger `OSError` wrap and non-string `id`/`event`/`hash`
   validation, `RecursionError` handling in `read_ledger` / `_parse_record`
   / `ingest` / `decide`, `_append_ledger` and record-write `OSError`
   wraps, `_decisions` skipping non-string ids, `RequestError` import).
   The three-way merge interleaved them cleanly; both survive everywhere.
   Deepen's `Store.verify()` was appended after `history()`, before
   `default_store_path`, exactly as deepen wrote it.

3. **`cli.py` — `cmd_ingest` (real conflict, harden vs polish).**
   Harden restructured the file read into one
   `try/except (OSError, UnicodeDecodeError)` and added a
   `RecursionError` branch to the JSON parse; polish added only a
   docstring over the pristine if/else shape.
   Resolution: polish docstring **plus** harden's restructured body,
   verbatim. Both the invalid-UTF-8 fix and the deep-nesting fix survive.

4. **`cli.py` — `main()` subparser block (real conflict, polish vs deepen).**
   Deepen inserted a `verify` subparser (alias `audit`) immediately
   before the `history` subparser; polish rewrote that same `history`
   subparser with a description, `DIR`/`ID` metavars and `--json` help.
   Resolution: deepen's `verify` block verbatim, followed by polish's
   expanded `history` block, with a single shared
   `p.set_defaults(func=cmd_history)`. Top-level `--help` therefore
   shows `{ingest,list,show,approve,deny,verify,audit,history}` with
   polish's epilog/examples intact (verified live).

5. **`cli.py` — module docstring (three-way, auto-resolved).**
   Polish expanded the header and added the everyday-loop paragraph;
   deepen added the `verify` usage line and extended the exit-code
   sentence with "or verify found integrity problems". All three
   pieces are present in merged; nothing was chosen over anything else.

6. **`cli.py` — `main()` docstring (merger amendment, noted).**
   Polish's docstring said exit 1 is only a refused decision/ingest.
   One sentence was extended to also name `verify` finding integrity
   problems (deepen's behaviour), so the combined docstring is true
   of the merged CLI. No code changed.

7. **`model.py` — no conflict.** Polish's docstrings (`canonical_json`,
   `content_hash`, `validate_id`, and the `normalise_request`
   normalisation contract) sit in different regions from harden's
   `import math` plus the iterative non-finite-float (NaN/Infinity)
   payload walk inside `normalise_request`. Diff audit: zero
   polish-unique or harden-unique lines lost.

8. **`README.md` — no textual conflict, one semantic overlap.**
   The three-way merge combined cleanly: polish's contents line,
   Quick start, run forms, notes, exit-code table, minimal request
   example, fallbacks, and refusals table, plus deepen's step 6
   (`verify`) in the everyday-commands block and its `verify`
   paragraph. The overlap was the exit-code line, which polish had
   turned into a table while deepen had amended the line itself for
   `verify`; the information would have survived in the `verify`
   paragraph but not in the table. Hand fix: table rows 0 and 1 now
   also state `verify`'s exit 0 / exit 1 meanings, and polish's
   Quick start was changed from "five steps" to six steps with a
   `verify` step 6, matching deepen's numbering of the everyday
   commands. No other README text was invented.

## Combined-behaviour notes (not conflicts, recorded for honesty)

- **verify × harden ledger validation:** deepen's `verify()` ignored
  ledger events with non-string ids in its cross-checks, but merged
  `read_ledger` (harden) now fails closed on a non-string
  `id`/`event`/`hash` and raises `StoreError`, so `verify()` reports
  such a ledger as a `ledger-readable` problem instead. Stricter,
  consistent with harden's documented fail-closed rule, and no deepen
  test contradicts it (its corrupt-ledger test passes via this path).
- **verify × harden record parsing:** a deeply nested record file now
  surfaces inside `verify()` as a `record-parse` problem (harden added
  `RecursionError` to `_parse_record`'s catches) rather than an
  exception. Deepen's own `content_hash` call inside `verify()` was
  left exactly as deepen wrote it; if it ever raised `RecursionError`,
  harden's last-resort guard in `cli.main` returns a clean exit 2.
  No test exercises that path because parsing catches deep nesting first.
- **Scope audits still clean:** a scan of merged `src/` for the
  `test_no_execution.py` forbidden strings (`subprocess`, `os.system`,
  `popen`, `eval(`, `exec(`, `socket`, `urllib`, `requests.`, and the
  auto-approval spellings including `--yes` / `--all`) finds none;
  the audit tests pass as part of the 62. Queue-only, no execution,
  no auto-approval, decisions bound to the exact record hash: all
  preserved. Stdlib only, no new dependencies, no version bump,
  LICENSE untouched.

## Anything suspicious

Nothing. No harden fix was dropped or weakened; the only lines absent
from merged relative to any lane are pristine lines superseded by
another lane, plus the two original one-line docstrings in `store.py`
(`ingest`, `decide`) that polish expanded. No unresolved conflict
remains; test caches created by the verification run were removed.
