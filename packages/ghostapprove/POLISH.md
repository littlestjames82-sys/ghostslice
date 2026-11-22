# GhostApprove v0.1 - Polish Round (Oct 14, 2026)

Sole-owner polish of the landed v0.1 (33 tests passing at parent
verification). House loop: audit first, then two distinct improvement
passes, every fix demonstrate-then-fix with a regression test.
No version bump, no release, no push, no publish, no announcements,
no spend, no network. Stdlib only. Only this folder was touched.

Final suite: **42 passed** (`python3 -m pytest tests -q`), the 33
pre-existing tests plus 9 new ones in `tests/test_polish.py`.

## Audit findings

Each finding was demonstrated against the unmodified core in a
scratch store before any code changed.

- **F1 (real, integrity) Decisions were not bound to the ingested
  hash.** `Store.decide` required an `ingested` ledger event for the
  id to exist, but never compared that event's hash to the record.
  Demo: ingest A and B, replace A's record file with B's content and
  hash (inner id edited to A, so the file stays internally
  consistent), then `approve A --hash <B's hash>` exited 0 and
  appended an approval for a request whose content was never
  ingested under A. The existing tamper test only covered in-place
  edits caught by the recompute check; wholesale replacement slipped
  past all three checks.
- **F2 (real, integrity) A record's inner id was never checked
  against the id it was loaded by.** `load_record` trusted any JSON
  object with `content` and `hash` keys. Combined with F1, identity
  of a record rested on its file name alone.
- **F3 (real, crash safety) Ingest wrote happily onto a torn
  ledger.** Demo: append a partial JSON line (crash mid-append, no
  trailing newline) to `ledger.jsonl`, then ingest a second request:
  exit 0, the new event merged onto the torn fragment (the ledger
  kept 2 lines and stayed permanently corrupt), and an orphan record
  was created. Every later read failed with exit 2, so the store
  accepted a write it could never read back.
- **F4 (real, robustness) Damaged record files crashed with
  tracebacks.** A record containing invalid UTF-8 made `show` exit 1
  with a traceback (`UnicodeDecodeError` is not caught by the
  `OSError`/`JSONDecodeError` handlers). A record containing a JSON
  array instead of an object made `list` traceback
  (`AttributeError` on `.get`). Both should be clean exit-2 store
  errors.
- **F5 (minor, durability) Record writes were not fsynced.** The
  atomic temp-plus-rename write never flushed the record bytes to
  disk before the rename, and no directory fsync followed, so a
  crash could leave a truncated record where a complete one had been
  acknowledged. Ledger appends already fsynced the file; the record
  path and the new-ledger case did not fsync the directory.
- **F6 (minor, clarity) No age anywhere.** `list` and `show` showed
  source, risk, and hash, but an operator scanning a queue had to do
  timestamp arithmetic to see what had been waiting longest (queue
  order helps, but is invisible once decided items are listed).
- **F7 (minor, robustness) `history` could crash on a hand-damaged
  ledger line** whose `hash` was explicitly null (`short_hash(None)`
  sliced `None`).

Checked and found sound in the audit (no change): supplied-hash and
recompute checks for in-place edits; double decision refused in all
four orders (approve/deny after approve/deny) with nothing appended;
refusals append nothing; status derivation is first-decision-wins
and decided records are never modified; `--hash` is argparse
`required=True` with no bypass flag; source contains no execution or
network machinery; generated ids cannot collide silently; duplicate
ingest ids refuse.

## Pass 1 - integrity and crash safety (src/ghostapprove/store.py)

- `decide` now also requires every `ingested` event for the id to
  carry the record's exact hash; a replaced record refuses with
  exit 1 and appends nothing (fixes F1).
- Records are parsed through one structural validator
  (`_parse_record`) used by `load_record` and `list_requests`: JSON
  object, inner id equal to the id it was loaded by, `content` an
  object, `hash` a string; anything else is a `StoreError`
  (fixes F2, F4). `UnicodeDecodeError` is caught in record and
  ledger reads and reported as a clean store error (fixes F4).
- `ingest` reads the ledger before writing anything: a corrupt
  ledger refuses the ingest (exit 2), writes no record, appends
  nothing (fixes F3). `_append_ledger` additionally never merges
  onto a torn final line: it terminates a newline-less tail first,
  leaving the fragment corrupt on purpose so reads keep failing
  closed until an operator repairs it.
- Record writes fsync the temp file before `os.replace` and fsync
  the directory after; ledger appends fsync the store directory
  when the file is first created; record temp names are randomised
  so two ingests can never share a temp path (fixes F5).

Probe re-runs after Pass 1: wholesale replacement refused (exit 1,
nothing appended); torn-ledger ingest refused (exit 2, ledger
byte-identical, no orphan record); invalid-UTF-8 and non-object
records fail cleanly at exit 2 with no traceback on show and list.

## Pass 2 - clarity and display robustness (cli.py, model.py, README)

- Human `list` rows and the `show` view now display the request's
  age (`age=just now`, `age=3h 20m`, `age=2d 4h`; `unknown` when the
  stored timestamp is missing or unparseable). Age is display only
  and feeds no decision logic (fixes F6).
- `short_hash` tolerates a missing or non-string hash and renders
  empty, so `history` survives a hand-damaged line (fixes F7).
- README brought into line with the code: the hash section now
  lists all four decision-time checks including the ingested-event
  hash binding; the store section documents the crash behaviour
  (fsync, atomic rename, torn-line handling, fail-closed damage);
  the commands section mentions the age display (fixes the doc side
  of F1/F3/F6).

## Regression tests added (tests/test_polish.py, 9 tests)

- `test_wholesale_record_replacement_refuses_decision` (F1)
- `test_record_inner_id_mismatch_fails_cleanly` (F2)
- `test_ingest_refuses_on_torn_ledger_and_writes_nothing`,
  including recovery after the operator removes the torn fragment
  (F3)
- `test_append_ledger_never_merges_onto_torn_line` (F3, unit level)
- `test_invalid_utf8_record_fails_cleanly` (F4)
- `test_non_object_record_fails_cleanly_in_list_and_show` (F4)
- `test_age_shown_in_list_and_show` (F6)
- `test_history_tolerates_null_hash_line` (F7)
- `test_no_new_flag_or_env_creates_a_decision`: bypass-style flags
  (`--force`, `--skip-hash`, `--auto`, `--approve-all`) are rejected
  and suggestive env vars (`GHOSTAPPROVE_AUTO_DECISION`,
  `GHOSTAPPROVE_DEFAULT_DECISION`, `GHOSTAPPROVE_SKIP_HASH`,
  `GHOSTAPPROVE_FORCE`, `GHOSTAPPROVE_DECIDE`) change nothing; the
  request stays pending with exactly one `ingested` event.

## What was deliberately left alone

- **Hard rules, untouched in spirit and in code:** no
  auto-approval path of any kind, no execution of approved actions,
  `--hash` required for every decision, record-before-decision.
  Pass 1 only ever made refusals stricter; it added no flag, no env
  var, and no new way to reach a decision. The only new surface in
  Pass 2 is display text (age) and a display helper.
- **Ledger tail truncation is still not detectable.** Deleting the
  last ledger line (for example a decision event) is
  indistinguishable from that event never having happened, so a
  truncated store could show a decided request as pending again.
  This is the same tamper-evident-not-tamper-proof limit recorded
  for the Agent Seatbelt audit log; closing it needs hash chaining,
  which is a format change for a later version's design gate, not a
  polish fix.
- **A planted second decision event in the ledger** is ignored by
  status derivation (first wins) rather than flagged; `decide` can
  never create one, and the raw event stays visible in `history`.
  Surfacing it as corruption is a possible later hardening, left
  out to keep this round's refusals byte-compatible.
- **`--store` precedence** (subcommand flag silently overrides the
  global flag) and the `--queue` / `GHOSTAPPROVE_QUEUE` /
  `GHOSTAPPROVE_HOME` aliases: confusing but harmless, documented
  in IMPLEMENTATION_A.md, and changing precedence mid-flight risks
  breaking harnesses that already rely on it.
- **Single-operator trust model** (`--by` is a label, not
  authentication) and manual file-drop ingest: v0.1 design
  decisions in PLAN.md, not polish scope.
