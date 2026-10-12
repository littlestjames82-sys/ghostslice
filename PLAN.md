# GhostSlice — Agent Context & Prompt Optimizer
Working name, prepared Oct 12, 2026. Origin: Ryan's "ContextCraft" proposal.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 12, 2026).

## Why this name
- GhostContext is taken, repeatedly, including a VS Code AI completion engine with AST-driven context gathering — too close to use.
- ContextCraft is taken, repeatedly, including a visual LLM context optimizer — too close to use.
- GhostSlice: no direct product found in search Oct 12, 2026. Names the core move (AST slicing), sits next to GhostCut in the family, and is not a generic "optimizer" (a crowded label: token-optimizer, ctxcraft, ContextIQ, token-goat all exist).

## The problem (Ryan's framing)
Developers running autonomous CLI agents (Claude Code, Aider, OpenClaw) burn tokens feeding whole files, node_modules, and stale docs into context. No visual way to see what the LLM will actually read before it runs.

## Position in the Ghost stack
- Agent Seatbelt governs what an agent DOES (consequential actions, approvals).
- GhostSlice governs what an agent READS (pre-flight, before any spend).
- Ghost Hands is the governed browser body.
That is a clean pre-flight -> action -> body story, no overlap.

## MVP (v0.1) — local web dashboard, not Tauri/Electron yet
Rationale: local web dashboard ships in days, proves the slicer, and matches Ghost Hands / Seatbelt Python track record. Desktop wrapper is a later gate, not MVP risk.

1. Scanner
   - Walk a project respecting .gitignore and a built-in default ignore (node_modules, dist, .git, binaries, lockfiles flagged separately).
   - Per-file token estimate (tiktoken-style counting where available, chars/4 fallback labelled as estimate).
2. Visual Context Tree
   - Tree / treemap heatmap by token cost, red = expensive, click to include / exclude.
   - Totals update live as you prune.
3. AST Slicer (Python + TypeScript/JS first)
   - Modes per file: Full, Signatures only, Interfaces/types only, Strip tests, Exclude.
   - Python: stdlib ast. TS/JS: regex + parser-lite in v0.1, tree-sitter as v0.2 upgrade if needed.
   - Preview sliced output side by side with token delta.
4. Pre-flight Estimator
   - "This run will ingest ~84,000 tokens ($X at selected model rate). Pruned: ~12,000 tokens ($Y)."
   - Model price table is local, editable, and dated. Never present prices as live.
5. One-Click Export
   - .claude_context bundle (folder + manifest.json with per-file mode, tokens, hash) and a single optimized prompt .md.
   - Export is a file the user drops in, no agent integration / no network in v0.1.

## Out of scope for v0.1
- Tauri/Electron packaging, auto-running agents, cloud sync, accounts, payments, telemetry.
- Languages beyond Python + TS/JS.
- Semantic / embedding pruning (v0.2 candidate).

## Build estimate
- Scanner + token counting + estimator: 2-3 days
- AST slicer (2 languages, 4 modes) + tests: 3-4 days
- Dashboard UI (tree heatmap, preview, export): 3-4 days
- Hardening, README, demo on a real Ryan repo: 1-2 days
Total: roughly 1.5 to 2 weeks to a verified v0.1, if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI + dashboard free, same pattern as Seatbelt / Ghost Hands.
- Paid candidate later only: hosted team presets / shared pruning profiles. Do not build paid layer before a free launch validates demand.

## Verification bar
- Slice a real repo (e.g. GhostBus or Seatbelt) and show before/after tokens with the agent task unchanged.
- Unit tests per slicer mode, golden-file fixtures.
- Export bundle re-imports and reproduces the same totals.

## Risks / honest notes
- Crowded niche: ContextIQ, ctxcraft, token-goat, token-optimizer MCP and others already chase token savings. Differentiation must be the visual pre-flight + AST slice preview + bundle export, not "saves tokens" alone.
- Token counts are estimates unless the exact model tokenizer is used. Label them.
- Model prices change; keep the table local and dated.

## Next gate
Ryan's go on: (1) GhostSlice as working name, (2) local web dashboard first, (3) Python + TS/JS only for v0.1.
