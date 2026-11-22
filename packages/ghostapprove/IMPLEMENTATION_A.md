# GhostApprove v0.1 - Implementation Notes (Agent A, core)

Built Oct 14, 2026 from `PLAN.md` (written by Agent A as step one, in
GhostSlice PLAN format). Python stdlib only, no network, no PyPI, no
GitHub push, no announcements, no spend.

## What was built (Agent A ownership: PLAN.md, src/**, pyproject.toml, this file)

```
PLAN.md                         working name, problem, stack position, MVP, gates, verification bar
pyproject.toml                  ghostapprove 0.1.0, zero dependencies, console script
src/ghostapprove/__init__.py    version 0.1.0, no-execution / no-auto-approval statement
src/ghostapprove/__main__.py    python -m ghostapprove
src/ghostapprove/model.py       request normalisation + canonical exact hash
src/ghostapprove/store.py       request records + append-only ledger, decision enforcement
src/ghostapprove/cli.py         ingest / list / show / approve / deny / history
```

Agent B owns tests/**, README.md, examples/** (REPORT_B.md). Their
examples landed with Seatbelt, GhostGuard, GhostDeploy, and Ghost
Bridge style request fixtures, all in the ingest shape defined here.

## Design decisions

- **Canonical exact hash (`model.py`).** Canonical content is the
  normalised request without `id`, ingest time, or hash: `source`,
  `action`, `summary`, `risk`, `diff`, `payload`, `requested_by`.
  Hash is sha256 over canonical JSON (sorted keys, compact separators,
  UTF-8), so identical content always hashes identically regardless of
  key order or whitespace in the producer file. `title` and
  `description` are accepted as ingest fallbacks for `action` and
  `summary` and normalised away. Risk must be one of low, medium,
  high, critical (default medium); any other value is refused with
  exit 2 rather than guessed. A supplied `id` is validated against a
  strict character set (path traversal guard) and must be unique.
- **Store layout (`store.py`).** One plain-files store (default
  `./.ghostapprove`, overridable with `--store` before or after the
  subcommand, or `GHOSTAPPROVE_DIR`; `--queue` is an accepted alias
  for `--store` on both positions, and `GHOSTAPPROVE_QUEUE` /
  `GHOSTAPPROVE_HOME` are accepted environment fallbacks, so the
  queue can be addressed by either name):
  `requests/<id>.json` immutable records and an append-only
  `ledger.jsonl`. Generated ids are `req-<hash prefix 8>-<random 6 hex>`.
- **Record-before-decision.** `Store.ingest` writes the record
  atomically (temp file plus `os.replace`) and appends the `ingested`
  ledger event (flush plus fsync) BEFORE returning success. `decide`
  additionally verifies an `ingested` event for the id exists before
  it will record anything; an id with a record file but no ingested
  event is refused.
- **Hash at decision time, three checks.** `approve` and `deny`
  require `--hash` (argparse `required=True`, there is no bypass,
  `--yes`, or `--all` flag anywhere). `Store.decide` refuses with
  exit 1 and appends NOTHING when: the supplied hash differs from the
  stored hash, the hash recomputed from the stored record content
  differs from the stored hash (record edited after ingest), or the
  request is already decided. On success exactly one event is
  appended carrying decision, id, exact hash, `by` (default
  `local-operator`, a recorded label, not authentication), optional
  note (deny also accepts `--reason`), UTC timestamp, and
  `"executed": false`.
- **Append-only ledger.** The ledger is only ever opened in append
  mode in this codebase. There is no delete, clear, undo, or edit
  command. Current status is DERIVED from the ledger, so editing a
  record's status field is impossible (records carry no status) and
  tampering with content is caught by the recompute check. A corrupt
  ledger line is exit 2, never a silent skip.
- **No execution, no auto-approval, by construction.** The source
  contains no network, subprocess, `os.system`, `eval`, or `exec`
  primitives (grep-verified on the `.py` files). The only function
  that writes a decision event is `Store.decide`, reachable only from
  the explicit `approve` / `deny` CLI commands with a required exact
  hash. Risk is a display and sorting label only; it appears in no
  decision logic. Approve output says verbatim: "decision recorded
  only - GhostApprove did NOT execute this action".
- **CLI exit codes.** 0 success, 1 decision refused (wrong hash,
  tampered record, already decided, unknown or unrecorded id,
  duplicate ingest id), 2 invalid request or store / IO error.
  `list` defaults to pending, oldest first (queue order, ingest
  timestamps carry millisecond precision so same-second ingests keep
  their order). `show` prints the full hash, diff verbatim, and
  payload pretty-printed. All read commands and decisions support
  `--json` with full hashes, never only the short form.

## Smoke test (run by Agent A, /tmp/ga-smoke, PYTHONPATH=src)

Fixtures: a GhostDeploy style high-risk deploy request with a diff
and payload, and an Agent Seatbelt style medium-risk file-delete
request with a payload.

| Check | Result |
|---|---|
| `ingest` both requests | exit 0 each; ids and full sha256 hashes shown; status pending |
| `list` | both pending, ingest order; rows carry source, risk, short hash, action |
| `show <id>` | full hash, summary, diff (deploy request), payload pretty-printed |
| `approve` with wrong hash | exit 1, refused, nothing appended |
| `approve` with exact hash (`--by Ryan --note`) | exit 0, one `approved` event, output states NOT executed |
| Second `approve` on decided request | exit 1, refused, still exactly one decision event |
| `deny` second request with exact hash (`--reason`) | exit 0, one `denied` event |
| `history` | 2 `ingested` then `approved`, `denied` in append order, with hash, decider, note |
| `list --status all` after decisions | statuses shown as approved / denied, none pending |
| Tamper: edit a stored record's summary after ingest, then approve with the originally shown hash | exit 1, refused: recomputed hash != stored hash; request stays pending |
| `approve` unknown id | exit 1, refused |
| `ingest` with invalid risk (`extreme`) | exit 2, refused rather than guessing |
| `python -m py_compile` on all modules | OK |
| Grep `.py` sources for urllib / socket / subprocess / os.system / eval / exec / http | clean (CLEAN_PY) |
| Files outside the store after an approval whose payload names a file and a deploy target | nothing created, modified, or executed; approval only appended to the ledger |

## Notes for parent verification

- Agent B's suite (tests/**) was run against this core by Agent A
  after the smoke test: **33 passed** (34.67s, `PYTHONPATH=src pytest
  tests -q`). One alignment fix came out of that run and is included
  above: B's harness addresses the store as `--queue` /
  `GHOSTAPPROVE_QUEUE`, so both are accepted as aliases for
  `--store` / `GHOSTAPPROVE_DIR`; the store layout B's tests assert
  (`requests/*.json` records plus `ledger.jsonl` at the store root)
  matches this core exactly, including their tampered-payload test,
  which edits a stored record and confirms the decision then refuses.
- Known v0.1 limits, by design (see PLAN.md out of scope): manual
  file-drop ingest only, no live adapters to Seatbelt / Guard /
  Deploy / Bridge, single-operator local store, `--by` is a label
  not authentication, no delete or undo.
