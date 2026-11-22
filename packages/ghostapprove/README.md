# GhostApprove
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostapprove/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostapprove/actions/workflows/ci.yml/actions)

**One local inbox for every "can I do this?" your agents ask, with the decision written down against an exact fingerprint.**

Agent Seatbelt asks before a consequential agent action. GhostGuard asks at its policy gate. GhostDeploy asks before a governed deploy. Ghost Bridge carries tasks that need a human yes or no. Until now each of those kept its own record, in its own shape, or no durable record at all.

GhostApprove is the shared queue in front of all of them. A tool writes a small JSON request file. You run one command to put it in the queue, read it in one plain format (what, why, how risky, identified by an exact hash), and record approve or deny against that hash. Later, anyone can audit exactly what was asked and what was decided, from two plain files on disk.

By Ghost Developer Studio. GhostApprove is the approval companion in the GhostSlice family.

Contents: [The one rule that matters](#the-one-rule-that-matters) · [Quick start](#quick-start) · [What you need](#what-you-need) · [The everyday commands](#the-everyday-commands) · [Why the hash is required](#why-the-hash-is-required) · [The request file](#the-request-file) · [Common refusals](#common-refusals-and-what-they-mean) · [The store](#the-store) · [What GhostApprove does not do](#what-ghostapprove-does-not-do)

## The one rule that matters

**GhostApprove records decisions. It never carries them out.**

Approving a request here does not run it, deploy it, send it, or change anything outside the GhostApprove store. The tool that asked reads the decision record and decides for itself what to do. There is no executor in this version, on purpose: an approval queue that quietly becomes an execution pipeline is exactly the failure this tool exists to prevent.

And nothing is ever approved automatically. No timeout, no risk rule, no `--yes`, no `--all`, no config or environment variable approves anything. A request stays pending until a human runs an approve or deny command naming its exact hash.

## Quick start

The whole workflow is six steps, and [`examples/WALKTHROUGH.md`](examples/WALKTHROUGH.md) shows a complete run with real output:

1. A producer writes a request file (see [The request file](#the-request-file)).
2. `ingest` puts it in the queue and prints its id and exact hash.
3. `list` shows what is waiting; `show <id>` shows one request in full.
4. `approve` or `deny` records a decision, but only when you name the exact hash from `show`.
5. `history` replays the ledger, so anyone can audit what was asked and what was decided.
6. `verify` checks the whole store still agrees with itself (read-only).

## What you need

Python 3.10 or newer. No accounts, no network, no dependencies.

Run it without installing, from the GhostApprove folder, by putting `src` on `PYTHONPATH` (the form used throughout this README):

```bash
PYTHONPATH=src python3 -m ghostapprove --help
```

Or install it to get the shorter `ghostapprove` command; the two forms are equivalent:

```bash
pip install -e .
ghostapprove --help
```

Every command and flag is also documented by the built-in help: `ghostapprove --help`, or per command, for example `ghostapprove approve --help`.

## The everyday commands

From the GhostApprove folder, with an optional store folder (default `.ghostapprove/` in the current directory, or `$GHOSTAPPROVE_DIR`):

```bash
# 1. Put a request in the queue
PYTHONPATH=src python3 -m ghostapprove --store .ghostapprove ingest examples/ghostbridge-request.json

# 2. See what is waiting (oldest first)
PYTHONPATH=src python3 -m ghostapprove --store .ghostapprove list

# 3. Read one request in full, including its exact hash
PYTHONPATH=src python3 -m ghostapprove --store .ghostapprove show req-ghostbridge-001

# 4. Decide, naming the exact hash you just read
PYTHONPATH=src python3 -m ghostapprove --store .ghostapprove approve req-ghostbridge-001 --hash <exact-hash-from-show> --by ryan
PYTHONPATH=src python3 -m ghostapprove --store .ghostapprove deny    req-ghostdeploy-001 --hash <exact-hash-from-show> --note "not yet"

# 5. Audit everything that happened, in order
PYTHONPATH=src python3 -m ghostapprove --store .ghostapprove history

# 6. Verify the whole store still agrees with itself (read-only)
PYTHONPATH=src python3 -m ghostapprove --store .ghostapprove verify
```

`verify` (alias `audit`) checks every record and ledger event, not just the one id being decided: each record recomputes to its stored hash, has exactly one `ingested` event carrying that hash, and any decision event names a recorded, ingested request with the exact hash and is the only decision for its id. It reports counts by status and one line per problem, exits 0 when the store is sound and 1 when it is not, and writes nothing either way.

Every command also accepts `--json`. `list` accepts `--status pending|approved|denied|all` and `--source <name>`. `history` accepts `--id <id>`. `verify` exits 1 (rather than 0) when it finds integrity problems. Human `list` rows and the `show` view also display how long a request has been waiting (age, display only; it never affects a decision).

Notes on the details:

- `ingest` also reads from stdin: pass `-` as the file path, as in `cat request.json | ... ingest -`.
- `--store` may be given before the command (as above) or after it; when both are given, the one after the command wins. The store path resolves in this order: the `--store` / `--queue` flags, then `$GHOSTAPPROVE_DIR` (the aliases `$GHOSTAPPROVE_QUEUE` and `$GHOSTAPPROVE_HOME` are also honoured), then `./.ghostapprove`.
- `--by` on `approve` / `deny` defaults to `local-operator`. It is a label recorded in the ledger, not an authentication.
- `deny` accepts `--reason` as an alias for `--note`. Either way, the text is recorded as the decision note.
- JSON output always carries the full hash; only the human `list` and `history` views shorten it to 12 characters.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Success: the request was ingested, the decision was recorded, or `verify` found no problems |
| 1 | Refused: hash mismatch, already decided, unknown or unrecorded id, or a duplicate ingest id; or `verify` found integrity problems. Nothing was written |
| 2 | Invalid request or store error: bad JSON, a missing required field, an unknown risk value, or a damaged record or ledger. Nothing was written |

## Why the hash is required

The hash is a sha256 fingerprint of the exact request content, computed when the request enters the queue and shown everywhere the request appears. A decision is only recorded if all of these match at decision time:

1. The hash you supply equals the hash on record.
2. The hash recomputed from the stored record still equals the hash on record, so a record edited after you reviewed it cannot be approved as if it were the request you saw.
3. The `ingested` ledger event for that id carries that same hash, so a record file swapped wholesale for a different request cannot be approved under this id.
4. The request is still pending, so it can never be decided twice.

If any check fails, the decision is refused and **nothing is written**. A recorded approval is evidence that a human saw a specific hash and decided. It is not proof that the originating tool acted, or acted correctly, and GhostApprove's own output says "decision recorded" for exactly that reason.

## The request file

One JSON file per request. Required: `action` (what is being asked) and `summary` (why, in plain words). The smallest useful request is:

```json
{
  "action": "Post a short build-status note to the shared board",
  "summary": "Keep the board current after the build dispatch.",
  "source": "ghostbridge",
  "risk": "low"
}
```

With no `id` in the file, one is generated at ingest. Also recognised:

| Field | Meaning |
|---|---|
| `source` | Who is asking: `seatbelt`, `ghostguard`, `ghostdeploy`, `ghostbridge`, `manual`, or any short producer name |
| `risk` | `low`, `medium`, `high`, or `critical`. Defaults to `medium`. Any other value is refused, not guessed |
| `diff` | Optional change summary or unified diff text, shown verbatim |
| `payload` | Optional JSON describing the exact action the producer would take |
| `requested_by` | Optional label for who or what raised the request |
| `id` | Optional. Must be unique; re-using an existing id is refused. Generated from the content hash when omitted |

Two producer conveniences are normalised at ingest: `title` is accepted as a fallback for `action`, and `description` as a fallback for `summary`. The stored record and the hash always use the canonical `action` and `summary` names, whichever spelling the producer wrote.

Producers: **never put a raw secret value in a request.** Name a secret by reference only. The store is a local file, but treat it as sensitive anyway, and keep it out of git.

Four ready-made requests are in `examples/` (one per source), with a worked run in `examples/WALKTHROUGH.md`.

## Common refusals and what they mean

A refusal is the tool working as designed: it writes nothing and explains itself on stderr. The ones an operator is most likely to meet:

| Message (paraphrased) | Exit | What happened, and what to do |
|---|---|---|
| `hash mismatch: supplied --hash does not equal the exact hash on record` | 1 | The hash you passed is not the hash `show` prints for this id. Re-run `show <id>`, copy the full hash exactly, and try again |
| `the record was edited after ingest` | 1 | The stored record no longer hashes to the hash on record. Do not decide it: ask the producer to re-issue the request so it is ingested cleanly |
| `is already approved` / `is already denied` | 1 | The request already has a decision, and a request can only be decided once. Check `history --id <id>` to see who decided it and when |
| `no such request` | 1 | No record exists under that id. Check the spelling against `list --status all` |
| `has no 'ingested' ledger event` | 1 | A record file exists without its ledger event, so it was never properly ingested. Treat the store as damaged (below) |
| `request id already exists` | 1 | `ingest` refuses to overwrite a record. Give the new request a different id, or drop its `id` and let one be generated |
| `request requires a non-empty string 'action'` (or `'summary'`) | 2 | The request file is missing a required field. Fix the file; `title` / `description` are accepted fallbacks for `action` / `summary` |
| `'risk' must be one of low, medium, high, critical` | 2 | An unrecognised risk value is refused, never guessed. Fix the file and ingest again |
| `ledger line N is corrupt` / `request record ... is malformed` | 2 | The store is damaged and every operation fails closed until an operator repairs the file by hand. Nothing is silently skipped or repaired by guessing |

## The store

```
.ghostapprove/
  requests/<id>.json   one record per request, never edited after ingest
  ledger.jsonl         append-only events: ingested, approved, denied
```

A decision is an appended ledger line, never an edit to the record, and there is no delete, clear, or undo command. Refused decision attempts are shown to the operator and are not written to the ledger: the ledger records facts, not attempts. Any status you see can be reproduced from these two files alone.

Writes are crash-conscious: a record is fsynced and atomically renamed into place before its ledger event is appended, ledger appends are fsynced, and a new event is never merged onto a torn (partial) final ledger line. Damage fails closed: if the ledger or a record cannot be read back exactly, ingest and decisions refuse with an error and write nothing until an operator repairs the file. Nothing is ever silently skipped, repaired by guessing, or decided around.

## What GhostApprove does not do

- It does not execute, dispatch, deploy, or send anything. Ever, in this version.
- It does not approve anything automatically, and low risk is a display label only.
- It does not talk to Seatbelt, Guard, Deploy, or Bridge. No polling, no webhooks, no server, no network at all. A producer writes a file; a human ingests it.
- It does not authenticate the human. `--by` is a recorded label on a single-operator local store, not an identity proof.
- It does not edit or delete requests or decisions.

## Pricing

Not decided, not public. The core follows the house MIT pattern; no pricing or release has been set for GhostApprove.

---
<!-- ghost-studio-footer -->
## More from Ghost Developer Studio

Ghost Developer Studio builds developer tools, AI-agent safety software, and practical apps, and sells by showing working software, not slide decks.

- [Roadmap board](https://github.com/littlestjames82-sys/ghost-roadmaps): where every studio product stands
- [Agent Seatbelt](https://github.com/littlestjames82-sys/agent-seatbelt): deterministic guardrails for AI coding agents
- [Ghost Hands](https://github.com/littlestjames82-sys/ghost-hands): governed, recorded, replayable agent hands
- [GhostSlice](https://github.com/littlestjames82-sys/ghostslice): agent context and prompt optimizer
- [GhostIDE](https://github.com/littlestjames82-sys/ghostide-android): fully offline AI code editor for Android
- [All studio projects](https://github.com/littlestjames82-sys?tab=repositories)
