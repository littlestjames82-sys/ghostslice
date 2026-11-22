# GhostReplay - Agent Session Learner for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #6 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostReplay: it replays what an agent session actually consumed, turn by turn, and shows where the tokens went.
- Naming caution recorded, not hidden: GhostGuard already has a replay add-on in the family (policy backtest over recorded trails, built Oct 10, 2026). These are different jobs (policy replay vs session context replay), but the shared word could confuse the catalog. Reserve alternative: GhostTrace. The build gate must pick one name deliberately with this collision on the table.
- Treat as a working name until that gate decision and a name check run, same discipline as GhostSlice Oct 12.

## The problem
Every Slice profile today is hand-tuned or generated once by `ghostslice init` from static signals. Real usage disagrees with static guesses:
- Files sent in every bundle that the agent never references.
- The same file re-read turn after turn because nothing cached the lesson.
- Symbols the agent keeps asking to see in full after getting signatures, a signal the mode is wrong for that task type.
- Prompts that re-explain the same project rules each session (a GhostRecall gap the session data can prove).

Nobody sees this because session transcripts are long, messy, and never analysed against the bundle that produced them. So teams keep paying for the same waste every day and call it the cost of agents.

## Position in the Ghost stack
- GhostSlice creates bundles from static project analysis.
- GhostVerify checks a bundle statically (graph reachability) and a patch after a run.
- GhostReplay learns from *actual runs*: what was sent, what was used, what was re-asked for. Its output is a better Slice profile, not a verdict.
- GhostBench measures controlled comparisons. Replay measures uncontrolled real work. Bench is the lab, Replay is the field data, they must not be merged into one number.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Manifest as ground truth for "sent": Replay joins a transcript to the bundle manifest (bundle hash recorded in the session notes or matched by file set) to know exactly what context the agent had, at what mode.
- Estimator + prices: wasted and re-read tokens are costed with the same estimator and local dated `prices.json`, labelled estimates. Provider-reported usage figures, when a transcript carries them, are recorded separately as reported, never blended with estimates.
- Profile format: Replay's deliverable is a proposed `.ghostslice.json` diff (mode changes, excludes, entry-point pins) with evidence per change. It uses Slice's profile loader rules: unknown keys fail loudly, invalid proposals never apply.
- History ledger: Replay summaries append to a `.ghostreplay-history.jsonl` and can roll into Slice history trends (cost per session over time, waste % trend).
- Secrets discipline: transcripts contain prompts, code, and sometimes keys. Replay output follows Slice guard rules: findings are path + line + type only, and the analysis report never quotes a secret-shaped string.
- Dashboard pattern: a session view in the spirit of Slice's dashboard (turn timeline, token heat per file across turns), local only, rendered textContent-only following the Slice v1.0.1 fix.

## MVP (v0.1) - local transcript analysis, one format first, propose-only
1. Ingest: `ghostreplay ingest <project> <transcript>`
   - v0.1 format: one transcript shape only, Claude Code session JSON/JSONL as saved locally, documented exactly. Other agent formats are adapters later, not launch claims.
   - Local files only. No fetching from any provider account, no API.
   - The user points Replay at a transcript they already have on disk. Replay does not record live sessions in v0.1.

2. Usage analysis: `ghostreplay analyse <project> <session>`
   - Sent vs referenced: files in the bundle never mentioned, read, or edited in the session (labelled "not referenced in transcript", not "not needed", because an agent may read silently in ways a transcript does not capture, see risks).
   - Re-reads: same file or symbol appearing as fresh context in N turns, with a token total.
   - Mode friction: symbols first given as signatures that the session later expands to full, counted per symbol. Repeated expansion is a profile signal.
   - Rule repetition: near-duplicate instruction blocks across sessions (Slice duplicate detection, line-shingle method) flagged as Recall candidates, with counts.
   - Per-session report `REPLAY.md` + `replay-report.json`: turns, tokens in, estimated waste by category, top re-reads, top never-referenced files (tokens each), friction list.

3. Profile proposal: `ghostreplay propose <project> <sessions...>`
   - Aggregates across at least 3 sessions by default (threshold in profile, a single session can be analysed but not proposed from, the report says why).
   - Emits a profile diff file with evidence per line: "exclude docs/legacy/**: present in 9/9 bundles, referenced in 0/9, 18,400 estimated tokens per session".
   - Proposal only. `ghostreplay apply` copies the diff into `.ghostslice.json` only after printing it and receiving an explicit yes in the terminal, and keeps the prior profile as `.ghostslice.json.bak` with a restore command. No silent auto-tuning ever, including in later versions without a separate Ryan gate.

4. Trend view: `ghostreplay trend <project>`
   - Sessions over time: estimated cost, waste %, re-read total, from the Replay ledger. Same style as `ghostslice history --trend`.

## Out of scope for v0.1
- Live recording, proxying, or intercepting sessions (that is GhostProxy territory).
- Any upload, sharing, benchmarking across users, or telemetry.
- Judging whether the agent's *answers* were good. Replay measures context use, Bench Tier B measures task outcomes.
- Auto-applying profile changes, auto-deleting files from bundles mid-session.
- Formats beyond the one documented transcript shape, and any scraping of a provider's web UI for history.

## Build estimate
- Transcript parser for the one v0.1 format + bundle join: 3-4 days
- Analysis categories (referenced, re-reads, friction, repetition): 3 days
- Proposal generator with evidence + safe apply/restore: 2 days
- Trend ledger + report + tests (fixture transcripts with planted waste, a zero-waste fixture that must propose nothing): 2-3 days
Total: roughly 1.5 to 2 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice.
- Paid candidate later only: team-level session analytics across a shared ledger. That would need its own privacy review and is not implied by v0.1.

## Verification bar
- Planted-waste test: a fixture session that re-reads one file 5 times and never references another must produce both findings with correct token totals, and a proposal citing them.
- Zero-waste test: a clean fixture session proposes an empty diff. A tool that always finds savings is inventing them.
- Privacy test: a fixture transcript with a planted secret-shaped string yields reports and logs with zero occurrences of that string (scan all outputs).
- Reproducibility: same transcript + same bundle manifest gives byte-identical `replay-report.json` totals on re-run.

## Risks / honest notes
- Transcript incompleteness is the central risk: what a transcript omits (silent reads, provider-side context) can make a used file look unused. Every "never referenced" claim in copy and reports must carry that qualifier, and proposals are evidence-for-a-human, not auto-truth. This is why apply always needs a human yes.
- Format fragility: the one supported transcript shape will change upstream. Pin the tested version/shape in the README, fail loudly on an unrecognised shape rather than analysing it badly.
- Transcripts are sensitive: they can hold proprietary code and personal prompts. Local-only, no network, and reports stored in the project by the user's choice are hard rules, in the README in plain words.

## Next gate
Ryan's go on: (1) name decision, GhostReplay vs GhostTrace given the GhostGuard replay collision, (2) one transcript format only in v0.1, (3) propose-only rule, profile changes always need an explicit human yes, (4) build slot: Replay is #6 in the suite.
