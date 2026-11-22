# GhostLedger — MERGE record (Oct 18, 2026)

Merger of the three improvement lanes onto a fresh copy of the
pristine tree (`~/workspace/ghostledger/`, never edited, nothing
pushed). Lanes applied in order: harden, then polish, then deepen.
Three-way merges were done per file against pristine as the base;
every conflict was resolved by hand so both sides survive.

## Final test counts (all run: `python3 -m pytest -q`)

- Pristine baseline: 44 passed
- harden lane: 59 passed (44 + 15 new in `tests/test_harden.py`)
- polish lane: 44 passed (docs/help only, no new tests)
- deepen lane: 56 passed (44 + 12 new in `tests/test_verify.py`)
- **merged: 71 passed** (44 + 15 + 12, the full union; zero failures)

Merged passes at least the best lane (59) and has zero new failures
versus every lane, since every lane's tests are present and green.

## Files by source lane

Copied from a single lane (no other lane touched them):

- `examples/README.md` — polish
- `src/ghostledger/__init__.py` — polish (docstring)
- `src/ghostledger/__main__.py` — polish (docstring)
- `src/ghostledger/verify.py` — deepen (new)
- `tests/test_harden.py` — harden (new)
- `tests/test_verify.py` — deepen (new)

Hand-merged (multiple lanes):

- `src/ghostledger/cli.py` — harden + polish + deepen (see conflicts)
- `src/ghostledger/ingest.py` — harden + polish (clean 3-way merge;
  one docstring line hand-adjusted, see below)
- `src/ghostledger/ledger.py` — harden + polish (2 conflicts)
- `src/ghostledger/prices.py` — harden + polish (1 conflict)
- `src/ghostledger/report.py` — harden + polish (clean 3-way merge:
  harden's `_one_line`/`_md_cell` escaping plus polish's docstrings)
- `README.md` — polish + deepen (1 conflict; deepen's verify
  Quickstart line, "Checking the books" section, Commands row, and
  Layout note all landed in polish's rewritten README)

Unchanged from pristine: everything else (`PLAN.md`, `POLISH.md`,
`IMPLEMENTATION_A.md`, `REPORT_B.md`, `LICENSE`, `pyproject.toml`,
`src/ghostledger/prices.json`, examples data, remaining tests).

## Conflicts and how they were resolved

1. **cli.py module docstring** (polish rewrite vs deepen edit):
   kept polish's fuller text; its exit-code sentence now carries
   deepen's fact: exit 1 also means audit problems found
   (`verify`). Deepen's `verify [--json]` line was already in the
   subcommand list. Also reconciled polish's `_EPILOG`: added a
   `ghostledger verify` example and the same exit-1 wording, and
   gave deepen's verify parser a polish-style description plus a
   `--json` help string (help text only, no behavior change).
   All harden cli logic (ISO `--at`/`--since`/`--until` validation,
   widened import error handling, OSError → exit 2 on ledger/report
   writes) and deepen's verify handler are present verbatim.

2. **ledger.py `is_secret_key`** (harden logic vs polish docstring
   on adjacent lines): kept harden's logic in full (count keys kept:
   `tokens`, `token_count`, `*_tokens`, `*_token_count`,
   `tokens_in/out`; singular `*_token` dropped as a credential) and
   rewrote the docstring to describe exactly that rule. The module
   docstring's secrets bullet was adjusted to match. No harden fix
   was dropped or weakened.

3. **ledger.py `make_entry`** (same pattern): kept polish's full
   parameter/return docstring (with one added sentence: a non-string
   `at` is treated as missing) and harden's code line
   `at = at if isinstance(at, str) and at else _now_iso()` with its
   comment. `load_entries` likewise carries polish's docstring
   (extended with the non-file case) over harden's `OSError` raise,
   and harden's `_safe_int`/`_safe_cost` tolerant accumulation is
   intact.

4. **prices.py `load_price_table`** (polish docstring claimed all
   candidates are passed over when malformed; harden made an
   explicit `--prices` table strict/raise): kept harden's strict
   explicit branch and tolerant fallback chain untouched, and
   rewrote the docstring to state both rules accurately. Harden's
   `_rates_of`/`model_rates` guards (non-dict entries skipped,
   negative/non-finite rates unusable) and polish's `model_rates` /
   `estimate_cost_usd` docstrings are all present.

5. **README.md exit-code paragraph** (polish vs deepen): kept
   polish's paragraph and Troubleshooting link; the exit-code
   sentence now includes deepen's "or audit problems found
   (`verify`)". Also added a Contents entry for the verify section
   and a `ghostledger verify` line in Common workflows.

6. **ingest.py Bench docstring** (not a textual conflict; the clean
   merge left polish's docstring describing the pre-harden estimate
   rule): adjusted one sentence so the docs match harden's behavior
   — the estimate is the full count only; a task with no full count
   books no estimate, never its own actual. Harden's `_int`
   bool/non-finite guards, non-dict `corpus` guard, and
   case-insensitive `.jsonl` detection are all present alongside
   polish's docstrings.

## Cross-lane interactions checked

- `verify.py` imports `is_secret_key` from `ledger.py`. Harden's
  stricter version keeps booked token-count fields
  (`total_tokens`, `input_tokens`, …) non-secret, so a clean booked
  ledger still verifies clean, while a planted `access_token` field
  is now also caught by verify. Verified by hand: add → verify
  exit 0; tamper with `access_token` → verify flags `secret_field`
  by key name only, exit 1; garbage `--at 2026-02-30` → exit 2;
  `--help` lists all five subcommands.
- No `IMPROVE.md` from any lane is present in the merged tree.
- No conflict markers remain; all modules compile.

## Anything suspicious

- Nothing dropped: every harden fix listed in its IMPROVE.md was
  confirmed present in the merged tree by diff inspection before
  the test run.
- Polish's README troubleshooting/docs describe pre-existing output
  quirks honestly; none were changed by this merge.
- Deepen's known caveat stands: `examples/sample-history.jsonl`
  uses illustrative ids, so `verify` flags every sample entry with
  `id_mismatch` — expected and documented in the merged README.
