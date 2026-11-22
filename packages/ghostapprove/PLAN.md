# GhostApprove - One Local Approval Queue for the Ghost Stack
Working name, prepared Oct 14, 2026. Wave 3 tool #16 for GhostSlice / Ghost Developer Studio.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostApprove: plain job, plain name. It is the one inbox where a human approves or denies what agents asked to do.
- Checked against the family: Seatbelt, Guard, Deploy, and Bridge each have their own approval surface. Approve does not replace any of them, it queues and records their requests in one place. No claim of a live product search yet. Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostInbox (describes the view, not the decision record, which is the point), GhostGate (too close to Guard's gating language and implies enforcement, which v0.1 must not claim).

## The problem
Ryan runs agents and governed tools all day, and approval requests arrive in at least four different places:

- Agent Seatbelt asks before a consequential agent action.
- GhostGuard asks at its policy gate.
- GhostDeploy asks for an exact-hash approval before a governed deploy.
- Ghost Bridge carries Antigravity tasks, notes, and capsules that need a human yes or no.

Each surface keeps its own record, in its own shape, or no durable record at all. There is no single queue a human can open, read in one format (what, why, how risky, what exactly, identified by an exact hash), decide once, and later audit. Decisions made in chat scroll away. A request that is edited after it was shown can be approved as if it were the request that was reviewed, because nothing binds the decision to the exact bytes reviewed.

Today the human is the integration layer, and the audit trail is memory.

## Position in the Ghost stack
- Agent Seatbelt governs what an agent DOES and when it must ask.
- GhostGuard governs policy at its gate.
- GhostDeploy governs deploys: record-before-execute, exact-hash approval.
- Ghost Bridge is transport and a queue of work between surfaces.
- GhostApprove governs NONE of those actions. It is the shared QUEUE and LEDGER in front of them: it ingests a request from any of them, presents it in one format, records the human decision against an exact hash, and hands the record back. The originating tool remains responsible for acting, or not acting, on that decision.

Story: any Ghost tool asks -> Approve queues and records -> human reviews summary, diff, risk, and exact hash -> human approves or denies -> originating tool reads the ledger and decides what to do itself.
No overlap: Approve never executes, deploys, sends, or runs the approved action in v0.1. It is a queue and a recorder only.

## How it pairs with the Ghost stack, concretely
Reuses, does not rebuild:
- GhostDeploy's discipline: record-before-decision and exact-hash binding. A request is written to disk and appended to the ledger as `ingested` BEFORE it can be listed, shown, or decided. A decision is valid only against the sha256 that was shown.
- GhostSlice's conventions: zero-dependency Python stdlib only, local-first, JSON plus JSONL artefacts a stranger can reproduce, estimates and hashes labelled exactly, no network, no telemetry.
- Request sources, not request engines: v0.1 defines one local JSON request shape that Seatbelt, Guard, Deploy, and Bridge style producers can each write with a file drop. Approve does not import, call, poll, or speak to any of them. A producer writes a file, a human (or a future adapter, out of scope here) runs `ghostapprove ingest <file>`.
- Secrets discipline, matching Slice v0.4 guard behaviour: Approve stores what it is given locally and shows it to the local operator only. Producers must not put raw secrets in a request; summaries and diffs should name a secret by reference, never by value. Approve never transmits anything anywhere.

Integration contract:
- Input: one local JSON file per request (shape in MVP item 1), ingested into a local store directory (default `.ghostapprove/` in the current directory, overridable with `--store` or `GHOSTAPPROVE_DIR`).
- Output: a per-request record file under `requests/`, an append-only ledger `ledger.jsonl` in the store, and human / `--json` CLI output.
- A decision is an appended ledger event, never an edit to the request record and never a deletion. Current status is derived from the ledger, so history cannot be rewritten silently by editing a status field.
- Consumers read the ledger or `ghostapprove show` / `history --json` output. Approve pushes nothing to them in v0.1.

## MVP (v0.1) - local CLI first, dashboard panel later
Rationale: same as Slice v0.1. CLI proves the queue and ledger on real requests in days. A panel, tray, or phone view is v0.2 once the record format is trusted.

1. Request shape and ingest: `ghostapprove ingest <request.json>`
   - Accepted fields: `source` (seatbelt, ghostguard, ghostdeploy, ghostbridge, manual, or any short producer string), `action` (what is being asked, required), `summary` (why, in plain words, required; `title` / `description` are accepted as fallbacks at ingest and normalised), `risk` (low, medium, high, critical; default medium, any other value is refused, not guessed), `diff` (optional unified diff or change summary text), `payload` (optional JSON value describing the exact action the producer would take), `requested_by` (optional), `id` (optional; if supplied it must be unique and safe, if not one is generated from the content hash plus a random suffix).
   - Canonical content is the normalised request without `id`, ingest timestamp, or hash. The exact hash is `sha256` over the canonical JSON (sorted keys, compact separators, UTF-8). It is computed at ingest, stored in the record, shown everywhere, and is the identity of what was reviewed.
   - Record-before-decision: ingest writes `requests/<id>.json` atomically (temp file plus rename) and appends the `ingested` ledger event BEFORE printing success. A request that is not in the ledger does not exist and cannot be decided.
   - Re-ingesting byte-identical canonical content under a new id is allowed (two producers can ask the same thing); re-using an existing id is refused. No silent de-duplication, no silent overwrite.

2. Queue views: `ghostapprove list [--status pending|approved|denied|all] [--source <name>]` and `ghostapprove show <id>`
   - `list` defaults to pending, oldest first (a queue, not a feed). Each row: id, source, risk, action, and the short hash (first 12 hex characters).
   - `show` prints the full record: action, summary, risk, source, requested_by, ingest time, full exact hash, the diff verbatim if present, and the payload pretty-printed if present, plus current status and any decision (who, when, note) from the ledger.
   - Both support `--json` with the full hash, never only the short form.

3. Decisions: `ghostapprove approve <id> --hash <exact-hash>` and `ghostapprove deny <id> --hash <exact-hash>`
   - `--hash` is REQUIRED. There is no approve without naming the exact hash reviewed, no `--yes`, no `--all`, no default.
   - At decision time the CLI recomputes the hash from the stored record's canonical content. Three checks, all must pass or the decision is refused (exit 1, nothing appended):
     a. the supplied `--hash` equals the stored hash,
     b. the recomputed hash equals the stored hash (the record was not edited after ingest),
     c. the request is still pending (no earlier decision event in the ledger).
   - On success exactly one event is appended to `ledger.jsonl`: decision, id, exact hash, decider (`--by`, default `local-operator`), optional `--note` (deny also accepts `--reason` as its note), and a UTC timestamp. The request record file is never modified.
   - On success the output says plainly: decision recorded, action NOT executed. Approve has no executor in v0.1 and approval changes nothing outside the store.
   - NO auto-approval ever: no timeout approval, no risk-based approval, no rule, config, environment variable, or flag that approves, in any code path. Low risk is a display label only. This is a hard gate, not a default.

4. History and audit: `ghostapprove history [--id <id>]`
   - Prints ledger events in append order: ingested, approved, denied, plus refused attempts are NOT written to the ledger (a refusal is a CLI outcome, exit 1, shown to the operator; the ledger records facts, not attempts). Supports `--json`.
   - The ledger is append-only in code: no command edits, truncates, or deletes a ledger line or a request record. There is no delete, clear, or undo command in v0.1.

5. Store layout
   ```
   .ghostapprove/
     requests/<id>.json    one immutable record per request (canonical content + hash + ingest time)
     ledger.jsonl          append-only events, one JSON object per line
   ```
   - The store is plain files so it can be inspected, backed up, and reproduced with no tooling. A missing or corrupt record or ledger line is an error (exit 2), never a silent skip and never a default approval.

## Out of scope for v0.1
- Executing, dispatching, deploying, sending, or otherwise carrying out any approved action. Recorded decisions are read by the originating tool, outside Approve.
- Auto-approval, approval rules, delegation, quorum, or expiry-with-approval. Pending requests stay pending until a human decides or the store is removed by the operator outside the tool.
- Any network: no server, no polling of Seatbelt / Guard / Deploy / Bridge, no webhooks, no sync, no accounts, no telemetry.
- Authenticating the human. v0.1 is a local single-operator store; `--by` is a recorded label, not an identity proof, and copy must say so.
- Editing or deleting requests or decisions, importing another tool's history, or migrating stores.
- Cloud, paid layer, pricing. None decided, none built.

## Build estimate
- Request normalisation + canonical hash + store (atomic record, append-only ledger): 2-3 days
- CLI (ingest, list, show, approve, deny, history) with hash checks and `--json`: 2 days
- Tests (hash tamper, wrong hash, double decision, record-before-decision, no-execution and no-auto-approve audits), README, demo with Seatbelt / Deploy / Bridge style fixtures: 2-3 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through. The risky part is not the code, it is keeping every future adapter honest about the no-execution boundary; v0.1 avoids it by having no adapters at all, only a file shape.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team approval history / multi-operator store. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Hash binding test: ingest a request, `show` it, approve with the shown hash succeeds and appends exactly one event; approve with any other hash is refused and appends nothing.
- Tamper test: edit a stored request record after ingest (change summary, risk, or payload), any decision attempt is refused because the recomputed hash no longer matches, and the request stays pending.
- Double decision test: a second approve or deny on a decided request is refused; the ledger still holds exactly one decision event for that id.
- Record-before-decision test: a decision against an id that was never ingested is refused; every decided id in history has an earlier `ingested` event for the same hash.
- No-execution test: approving a request whose payload names a file or command changes nothing outside the store: no file created, modified, or deleted, checked by a fixture tree hash before and after.
- No-auto-approve audit: no code path, flag, config, or environment variable produces a decision event without an explicit approve / deny command carrying the exact hash. Greppable and tested.
- Every status a stranger sees is reproducible from `requests/` plus `ledger.jsonl` alone.

## Risks / honest notes
- A recorded approval is evidence a human saw a hash and decided, not proof the originating tool acted, or acted correctly. Copy must say "decision recorded" not "action completed."
- File-drop ingest is manual in v0.1. That is deliberate: live adapters are exactly where an approval queue quietly becomes an execution pipeline, so they are separate, later, per-producer decisions.
- `--by` is a label on a single-operator local store, not authentication. Multi-operator identity is a v0.2 design question, not a v0.1 claim.
- Storing diffs and payloads locally means the store itself is sensitive. It belongs in a gitignored local directory, and producers must reference secrets, never embed them.

## Next gate
Ryan's go on: (1) GhostApprove as working name, (2) CLI-first, file-drop ingest only, no live adapters in v0.1, (3) hash-required decisions with no bypass flag, (4) no execution and no auto-approval as permanent v0.1 gates, (5) build position inside Wave 3.
