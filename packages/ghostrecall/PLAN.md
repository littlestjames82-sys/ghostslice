# GhostRecall - Project Memory Slicer for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #2 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostRecall: it recalls what the project already decided, and it slices that memory the way GhostSlice slices code.
- Reserve alternative: GhostMemory (generic, crowded label, likely taken in the agent-memory niche). Recall keeps the verb and avoids promising a general memory store.
- Treat as a working name until a name check runs at build gate, same discipline as GhostSlice Oct 12.

## The problem
GhostSlice gives an agent the code, sliced well. It gives it almost nothing about why the code is that way:
- Decisions made in a prior session, a PR discussion, an ADR, or a chat thread.
- Things already tried and rejected, and why.
- Project rules that live in a founder's head, a long README, or scattered notes: naming, gates, "never do X", pricing calls, publish holds.

So every new agent session re-derives, re-proposes rejected routes, and re-asks settled questions. In Ryan's own stack this is concrete: Goliath is reserved for a non-agent product, GhostSlice has no PyPI publish and no announcements, Koyeb is a closed route. An agent without that memory will happily propose all three.

Code context without decision context is half a briefing.

## Position in the Ghost stack
- GhostSlice governs what an agent READS about the CODE.
- GhostRecall governs what an agent READS about the PROJECT: decisions, history, rules, prior attempts.
- GhostVerify checks the combined bundle was enough.
- Agent Seatbelt governs what an agent DOES. Ghost Hands is the body.

Recall does not replace a notes app or a vector database. It is a slicer and exporter with the same discipline as Slice: local, visual cost, modes, manifest, checkable bundle.

## How it pairs with GhostSlice, concretely
Two bundles become one briefing:
- Slice exports `.claude_context/` (code).
- Recall exports `.ghost_memory/` (decisions/history/rules).
- A combined export, `ghostrecall bundle`, writes one folder containing the Slice manifest reference plus the Recall manifest, and a single merged `PROMPT.md` with a hard token budget split the user controls (default suggestion: 80% code / 20% memory, labelled a default, not a finding).

Reuses, does not rebuild:
- Scanner and token estimator: same walk, same ignore discipline, same estimator version stamp and local `prices.json`. Memory sources get token costs and heat ranking exactly like files.
- Modes engine: Recall defines memory modes that map onto Slice modes, see MVP.
- Profile: extends `.ghostslice.json` with a `recall` section. Unknown keys fail loudly, same as Slice lint/profile behaviour. No silent second config file to drift.
- Ledger: writes recall selections into the same history story so `ghostslice history` style trend views can later show code tokens vs memory tokens per export.
- Secrets guard: runs Slice's secrets scan over every memory source before export. Memory files are *more* likely to contain keys, emails, and private notes than code. A finding blocks that item by default, redacted in all output (path + line + type only), matching Slice v0.4 behaviour.
- MCP: `recall_search`, `recall_bundle`, `recall_explain` tools on the same stdio pattern, capped payloads.

What Recall must NOT import: private Muse memory (`~/MEMORY.md`, `~/memory/`) by default. That is Ryan's assistant memory, not a project artifact. A project opts in by pointing Recall at its own sources inside the project. This boundary is a v0.1 rule, not a setting buried in docs.

## MVP (v0.1) - local CLI + one dashboard view, no embeddings
Rationale: keyword/TF-IDF selection is already proven in `ghostslice task` and needs no model, no network, and no vector store. Semantic retrieval is a v0.2 candidate only if TF-IDF demonstrably misses on real projects.

1. Memory sources (project-local only)
   - Markdown/text notes, ADRs, CHANGELOG, docs/ tree.
   - Git history: commit messages + PR-style summaries from the local git log, sliced by date/topic. Local git only, no hosting API in v0.1.
   - Agent session notes the project itself saved (for example BUILD reports, audit reports, roadmap files, like GhostSlice's own `audits/` and `MARATHON_20_REPORT.md`).
   - Explicit decision files: a simple, documented `DECISIONS.md` format (date, decision, reason, supersedes) that Recall parses into individual decision records. Freeform notes still work as plain sources, decisions just get structure when the format is used.

2. Memory slicer - modes per item
   - `full`: whole note / decision with reason.
   - `decision-only`: the decision line and date, reason stripped. The cheap default for settled rules.
   - `headings`: same treatment as Slice Markdown `headings` mode.
   - `recent`: last N decisions or log entries touching a file/topic, N from profile.
   - `exclude`: kept out, recorded in the manifest as excluded so absence is auditable.
   - Every decision record carries provenance: source file, line or commit, date. A recalled decision with no provenance is not exported. This is the anti-hallucination rule for the whole tool.

3. Task-focused recall: `ghostrecall recall <project> --task "..."`
   - TF-IDF over decision records + note sections + commit messages, ranked with token costs shown.
   - Rule pinning: items tagged as standing rules in `DECISIONS.md` or the profile are always included for their scope, even if TF-IDF ranks them low, and the report says they were pinned, not ranked.
   - Superseded decisions are shown as superseded or excluded, never silently served as current. If a source contradicts a newer decision in the same bundle, Recall flags the conflict rather than picking a winner.

4. Combined bundle: `ghostrecall bundle <project> --task "..." --fit <tokens>`
   - Calls GhostSlice export for code and Recall for memory under one total budget, using Slice's `--fit` ladder for code and decision-only downgrades for memory.
   - One merged manifest: per item, source type (code / decision / note / commit), mode, original tokens, sliced tokens, sha256.
   - `ghostrecall check <bundle>` verifies the combined manifest the same way `ghostslice check` verifies a code bundle.

5. Dashboard view
   - One extra panel in Slice's local dashboard (not a second server): memory heat list next to the code tree, pinned rules at top, include/exclude toggles, live combined total. Text rendered safely, following Slice v1.0.1's textContent-only fix.

## Out of scope for v0.1
- Embeddings, vector stores, cloud sync, shared team memory, accounts.
- Reading Muse's private memory, chat transcripts outside the project, email, or any source outside the project root the user pointed it at.
- Auto-writing decisions. Recall reads and slices project records; a human (or an agent with Seatbelt approval) writes `DECISIONS.md`. Auto-capture from sessions is a separate, later gate because wrong auto-decisions are worse than missing ones.
- Summarising sources with an LLM. Modes are extractive only in v0.1, so provenance stays exact.

## Build estimate
- Source walkers (notes/docs, git log, decision parser) + provenance model: 3-4 days
- Memory modes + TF-IDF recall + rule pinning + conflict flag: 3 days
- Combined bundle + fit + check + secrets carry-over: 2-3 days
- Dashboard panel + MCP tools: 2 days
- Tests (superseded-decision fixtures, secret-in-note fixtures, provenance completeness), README, demo on GhostSlice itself (its audits + roadmap as the memory corpus): 2 days
Total: roughly 1.5 to 2 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI + dashboard panel free, same pattern as Slice.
- Paid candidate later only: hosted team memory presets / shared decision libraries. Do not build before a free launch validates demand.

## Verification bar
- Provenance test: every exported memory item in the demo bundle traces to a file + line or a commit hash in the test project. Zero orphan items passes, any orphan fails the build.
- Superseded test: a fixture project with a reversed decision (like a publish hold that was later lifted) must never serve the old decision as current.
- Secrets test: a note fixture with a planted key is blocked and redacted.
- Real demo: combined bundle for a GhostBus task, code + memory, fits a stated budget and still contains the standing rules for that area, shown in the report.

## Risks / honest notes
- Stale memory is dangerous in a way stale code is not: code is the current state, a note may describe a state that changed. Dates + superseded handling + provenance are core features, not polish.
- TF-IDF will miss paraphrased decisions. v0.1 must show what was *not* selected on request (`--explain` style), so a miss is visible instead of silent.
- Scope creep into "AI memory platform" is the main risk. Recall stays a slicer/exporter paired with Slice. If it needs a server to work, the design has drifted.

## Next gate
Ryan's go on: (1) GhostRecall as working name, (2) project-local sources only, Muse private memory excluded by rule, (3) extractive modes only, no LLM summarising in v0.1, (4) build order: Recall is #2 of the four companions, after Verify.
