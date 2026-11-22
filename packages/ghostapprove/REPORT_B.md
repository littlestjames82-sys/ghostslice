# GhostApprove - Agent B Report (tests / README / examples)
Prepared Oct 14, 2026. Scope owned and edited by Agent B only: tests/**,
README.md, examples/**, this file. src/**, pyproject.toml, and PLAN.md
were read (read-only, after Agent A's core landed) but never edited.

## Result: PASS, 33/33 tests, run twice
`python3 -m pytest tests -q` from ~/workspace/ghostapprove:
- Final state: **33 passed, 0 failed, 0 skipped**, twice in a row
  (38.35s, 32.71s; subprocess-driven CLI tests, so not fast).
- Breakdown: fixtures sanity 6, ingest/list/show 8, decisions 10,
  history 5, no-execution/no-auto-approval audits 4.

## Honest run history
- Tests were first drafted against the task spec before Agent A's
  core existed (assumed `--queue`; examples used `title`/`details`).
  When A's PLAN.md + src landed mid-build, Agent B re-aligned to the
  real contract (below) and rewrote the examples to the real request
  shape. No test was loosened during alignment; two were made stricter
  (duplicate id now asserts refusal per PLAN, refused decisions now
  assert the ledger is byte-identical).
- First full aligned run: 32 passed / 1 failed. The failure was a bug
  in MY test (missing `load_example` import in test_decisions.py),
  not in the core. Fixed, full suite green twice after.
- No core defects were found. Agent A's core satisfies every item on
  its own PLAN verification bar that this suite covers.

## Contract the tests drive (Agent A's landed CLI, verified)
- `ghostapprove [--store DIR] ingest|list|show|approve|deny|history`,
  store also via `$GHOSTAPPROVE_DIR`, default `./.ghostapprove`.
  Store layout: `requests/<id>.json` + append-only `ledger.jsonl`.
- Request shape: `action` + `summary` required (`title`/`description`
  are producer fallbacks), `source`, `risk` in low|medium|high|
  critical (default medium, other values refused), optional `diff`,
  `payload`, `requested_by`, `id` (unique; reuse refused).
- Hash: sha256 over canonical JSON of normalised content (sorted
  keys, compact separators), computed at ingest, shown full in
  `show` / `--json`, short (12) in human `list` / `history`.
- Decisions: `--hash` REQUIRED. At decision time the core checks
  supplied == stored, recomputed-from-record == stored, and still
  pending; any failure refuses with exit 1 and appends nothing.
  Refusals are never written to the ledger. Decision events carry
  `"executed": false`. Exit codes 0 ok / 1 refused / 2 invalid.
- conftest.py keeps verb/flag fallbacks (add/submit, deny/reject,
  env-passed store) so small spelling differences would not rewrite
  test intent, but the PRIMARY forms exercised are exactly the landed
  CLI. If no entrypoint exists, behavioural tests FAIL with a
  "core not ready" message - they never skip to fake a green run.

## Adversarial coverage (required by the task)
- **Tampered hash argument**: one hex digit flipped; both approve and
  deny refuse, request stays pending, and the real hash still works
  afterwards (refusal is not a lockout).
- **Tampered stored record**: the record file's summary is edited
  after ingest; deciding with the original hash refuses because the
  core recomputes the hash from stored content. Request stays pending.
- **Tampered supplied hash field**: a request file carrying a bogus
  all-zero `hash` field is not trusted; the shown/stored hash is the
  computed one, never all-zeroes.
- **Double decision, all orders**: approve-after-approve,
  deny-after-approve, approve-after-deny, deny-after-deny all refuse;
  exactly one decision event exists per id.
- **Deny path**: records `denied` with note, status reads denied, and
  the request disappears from the pending list.
- **No hash, no decision**: approve without `--hash` refuses.
- **Record-before-decision**: deciding or showing an unknown id
  refuses cleanly (no traceback); every decided id in history has an
  earlier `ingested` event with the same hash.
- **Append-only history**: ledger bytes after later events have the
  earlier bytes as an exact prefix; refused attempts append nothing
  (ledger byte-identical); the request record file is byte-identical
  before and after a decision.
- **No execution**: approving the seatbelt example (whose payload
  names `examples/SHOULD_NOT_EXIST_seatbelt.txt` as its side effect)
  creates no file anywhere; plus a source audit asserts the core
  contains no subprocess/os.system/socket/urllib machinery and no
  auto-approval surface (`--yes`, `--all`, auto-approve spellings),
  and fake `GHOSTAPPROVE_AUTO_APPROVE` / `GHOSTAPPROVE_APPROVE_ALL`
  env vars change nothing (request stays pending).
- **Bad input**: invalid JSON refused, request missing `summary`
  refused, duplicate id refused with exactly one record file kept.

## Examples and README
- examples/: four sample requests, one per source (seatbelt high,
  ghostguard medium, ghostdeploy high with a diff summary,
  ghostbridge low). All fictional, no secret-shaped values (the sanity
  suite regex-checks this).
- examples/WALKTHROUGH.md: ingest x2, list, show, approve, deny, a
  refused double decision (exit 1), and history - every command run
  verbatim by Agent B on Oct 14, 2026 against the landed core.
  Content hashes reproduced exactly: ghostbridge
  add7e122a394fe3eb2969fbeab5d1ec83a776d63aaed275b54abcd8c331c7ca7,
  ghostdeploy fd7f7d7129903f4c244355991e44d15a9f8f892bfbaeca946d681f9e35170496.
- README.md: plain-words. Leads with the queue-only rule (records
  decisions, never executes, nothing auto-approved), the three hash
  checks, exit codes, the request-field table with the
  never-embed-a-secret warning, the store layout, what it does not
  do (no adapters, no network, `--by` is a label not authentication),
  and pricing stated as not decided.

## Gates honoured
Local only: no network use, no push, no publish, no announcements,
no spend. Behavioural tests run against throwaway stores in pytest
tmp dirs; the walkthrough used /tmp/ga-walk. No files outside the
Agent B ownership list were edited (Agent A's src/**, PLAN.md,
pyproject.toml, IMPLEMENTATION_A.md untouched).
