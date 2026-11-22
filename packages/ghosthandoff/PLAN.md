# GhostHandoff - Session Handoff Pack for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #25 for GhostSlice (Wave 4).
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostHandoff: plain job, plain name. When one agent or person stops and another continues, this builds the handoff pack the next one starts from.
- Checked against the family: GhostReplay learns patterns across many past session transcripts. GhostHandoff does not learn anything. It captures one session's state at stop time, from the repo, once. GhostPrimer (Wave 4, #24) is for the first session ever on a project; GhostHandoff is for session N handing to session N+1.
- Alternatives held in reserve: GhostBrief (implies advice or generated summary, which v0.1 must not produce), GhostRelay (collides with Ghost Bridge's hosted relay), GhostContinuity (accurate but long).

## The problem
Sessions end abruptly: context window fills, the laptop closes, a different agent or a person picks the work up tomorrow. The state that matters at that moment is real but scattered:

- Which branch, how far ahead or behind, what is committed and what is still dirty.
- What actually changed this session, as opposed to last week.
- Whether anything was verified, and what the last check actually said.
- What is half done: TODO markers, a stash, unpushed commits, a failing report.

Today the next session re-derives all of that by re-reading the repo, which costs tokens, takes time, and still gets things wrong (the classic failure: an agent assumes a change was committed when it is sitting uncommitted in the working tree, or trusts a verification report from three days ago as if it were current).

No Ghost tool assembles the stop-time snapshot. GhostSlice bundles code context, GhostVerify judges slices and patches, GhostReplay mines old transcripts after the fact. The moment of handoff itself is uncovered.

## Position in the Ghost stack
- GhostSlice governs what an agent READS.
- GhostVerify governs whether what it read was ENOUGH, and whether what it wrote back HOLDS.
- Agent Seatbelt governs what an agent DOES.
- GhostReplay learns across PAST sessions.
- GhostHandoff captures THIS session at stop time, for the NEXT session.

Story: agent works under Seatbelt with a Slice bundle, Verify checks the result, the session ends, Handoff packs the state, the next session (agent or human) starts from HANDOFF.md instead of from scratch.
No overlap: Handoff runs nothing, judges nothing, and learns nothing. It reports repo facts in one place, with each fact's source named.

## How it pairs with the Ghost stack, concretely
Reads, does not rebuild:
- Git state via read-only git commands only (status, log, diff stats, ls-files, stash list, rev-parse), run with optional locks disabled so git itself writes nothing back to the index.
- GhostVerify artifacts when present: `verify-report.json` verdict and `VERIFY.md`, quoted as found with their modification time, never re-run.
- GhostSlice artifacts when present: bundle directories (any folder holding a `manifest.json` in the top two levels) and the `.ghostslice-history.jsonl` ledger tail.
- GhostBench or test-runner traces when present: a Bench report file, or `.pytest_cache` lastfailed, reported as counts and timestamps, not re-run.
- TODO, FIXME, XXX, and HACK markers in the project's tracked and untracked-but-not-ignored files.

Integration contract:
- Input: a project path, an optional session window (`--since 2h`, an ISO time, or a git ref), an optional output directory.
- Output: `HANDOFF.md` (human and agent readable) + `handoff.json` (same facts, machine readable) in the output directory only. Default output is `./handoff-out` under the caller's working directory, never inside the described project unless the caller points `-o` there explicitly.
- The pack is small enough to paste into a fresh session or to include in a later GhostSlice bundle as a plain file.

## MVP (v0.1) - local CLI first
1. Build the pack: `ghosthandoff pack <project> [-o <dir>] [--since <when>] [--base <ref>]`
   - Git state: branch (or detached HEAD), short HEAD hash, upstream with ahead/behind counts, staged / unstaged / untracked file lists from porcelain status, stash entries.
   - Session changes: commits inside the session window (hash, subject, author, time) and the union of files they touched, plus working-tree diff stats (files changed, insertions, deletions) for staged and unstaged changes separately. The window is stated in the pack. Default window: the last 12 hours plus all uncommitted changes, because uncommitted work is always part of the handoff regardless of age.
   - `--since` accepts a duration (`2h`, `90m`, `3d`), an ISO date or datetime, or a git ref (then the session is `ref..HEAD`).
   - Verification status: every recognised report file found, with its kind, relative path, modification time, and a short extractive summary (a verdict field, a first line, a failure count). Staleness is shown, never hidden: a three-day-old report reads as three days old.
   - Open loops: derived only from facts above. Uncommitted files, unpushed commits, stash entries, open markers, a non-passing latest verdict, recorded test failures. Each loop names its source.
   - Next steps: short templated drafts generated from the open loops in a fixed priority order, each citing the fact it came from. If no loops exist, the pack says no next steps were derivable from repo facts. It never invents work.
2. Show a pack: `ghosthandoff show <pack-dir>` prints HANDOFF.md.
3. Safety and honesty rules, enforced in code:
   - Propose-only: there is no commit, send, push, or edit path anywhere in the tool. It writes only the two pack files, only in the output directory.
   - It never runs project code: no test execution, no build, no scripts from the described project. Git read-only subcommands and file reads are the whole surface.
   - Extractive only, no LLM: every sentence in HANDOFF.md is a template filled from a measured fact. Marker lines and report excerpts are quoted, truncated, and passed through a secret-shape redaction pass before they are written.
   - Caps are stated: marker list, file lists, and commit list are capped, and the pack says when a cap was hit and what the true total was where it is known.
   - Exit codes: 0 = pack built (degraded sections labelled, for example a project that is not a git repo still gets marker and report sections with the git section marked unavailable), 2 = could not build (project path missing or unreadable).

4. MCP tools (stdio, local only)
   - `build_handoff` and `read_handoff` with capped summary payloads, same discipline as the other Ghost tools (counts and pack paths, HANDOFF.md only on request and capped).

## Out of scope for v0.1
- Committing, pushing, sending, or posting the pack anywhere. Distribution is the human's job.
- Editing any file in the described project, including adding the pack to it.
- Running tests or any other project code to refresh verification status. Handoff reports the last recorded status with its age; re-verifying is GhostVerify's job.
- Summarising diffs or code with an LLM, and any generated prose beyond fixed templates.
- Learning across sessions, trend lines, or per-author analytics. That is GhostReplay's territory.
- First-session onboarding packs. That is GhostPrimer (#24).
- Cloud, accounts, telemetry, paid layer.

## Build estimate
- Git facts layer (porcelain parsing, window logic, diff stats): 1-2 days
- Marker scan + report discovery: 1-2 days
- Pack drafting (open loops, next steps, HANDOFF.md + handoff.json writers): 2 days
- MCP server, tests, README, demo on a real in-flight project: 2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Verify / Seatbelt.
- Paid candidate later only: team handoff history across repos, or a hosted pack shelf. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Fixture repo test: a repo with a known branch, 2 commits inside the window, 1 uncommitted modified file, 1 untracked file, 1 stash entry, 3 TODO markers, and a verify-report.json with a failing verdict. The pack must state every one of those correctly, in both HANDOFF.md and handoff.json.
- Read-only proof: the described project's file hashes and `git status` output are byte-identical before and after a pack run.
- No-invention test: a clean repo with no markers, no reports, and no loops produces a pack that says exactly that, with an empty next-steps list.
- Agreement test: every count in HANDOFF.md matches handoff.json from the same run.
- Non-git test: a plain folder still produces a pack, with the git section marked unavailable and exit 0.

## Risks / honest notes
- "This session" is a heuristic. Git does not record session boundaries, so the window is a stated approximation (default last 12 hours plus uncommitted work), never presented as exact.
- Marker scans have false positives: TODO strings inside docs, fixtures, and this tool's own test data will match. The pack lists file and line so a reader can judge, and caps keep it readable.
- Report discovery is by known file names and shapes. A verification result stored anywhere else will be missed, and the pack's coverage note says so.
- A handoff pack is only as fresh as the moment it was built. It carries its build time on its face and goes stale immediately after; it is a snapshot, not a live view (live staleness watching is GhostWatch's job).

## Next gate
Ryan's go on: (1) GhostHandoff as working name, (2) propose-only with no commit/send/edit path in v0.1, (3) no test execution, report status is quoted with its age, never refreshed by running anything, (4) default session window of 12 hours plus uncommitted changes, (5) build slot in Wave 4 as #25.
