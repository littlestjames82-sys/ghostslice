# GhostIndex - Cross-Project Local Search Index for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #26 for GhostSlice (Wave 4).
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostIndex: plain job, plain name. It indexes the projects a developer points it at, so an agent (or the developer) can find the right file before slicing anything.
- Checked against the family: GhostSlice cuts one project's context down. GhostAtlas draws a human map of one codebase. GhostRecall slices one project's memory files. GhostIndex is the finder across many projects: full-text search over code and docs the user named, returning small excerpts instead of whole files. No claim of a live product search yet. Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostFind (too generic, collides with shell habits), GhostSeek (implies semantic or AI search, which v0.1 is not; this is honest keyword full-text search).

## The problem
GhostSlice v1.0.6 slices a project the developer has already chosen. It does not answer the question that comes first: which project, and which file in it, holds the thing I half remember?

On a real machine with dozens of project checkouts, that question is answered today by:
- `grep -r` runs that dump whole matching lines with no ranking, no token sense, and no respect for a token budget, repeated from scratch on every question because nothing is indexed.
- Opening whole files in the agent's context once a candidate is found, paying full-file tokens to read the 12 lines that matter.
- The developer's memory, which does not scale past a handful of repos and is useless to an agent.

There is no local, offline, cross-project index in the Ghost stack that returns ranked, bounded excerpts an agent can act on, and that keeps working when the projects change because it updates by file hash instead of rescanning everything.

## Position in the Ghost stack
- GhostSlice governs what an agent READS inside one project (scanner, AST slicer, token estimator, bundle export).
- GhostIndex governs FINDING across projects: which root, which file, which lines, before any slicing decision is made.
- GhostVerify governs whether what was read was ENOUGH.
- Agent Seatbelt governs what an agent DOES. Ghost Hands is the governed browser body.

Story: Index (find) -> Slice (cut) -> Verify (check) -> agent runs under Seatbelt.
No overlap: Index never slices a bundle and never exports context packs; it returns excerpts with file, line range, and token estimates so Slice (or the agent) can decide what to pull in full. Atlas stays the human-readable map; Index is the machine-queryable finder underneath it.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Scanner discipline: mirrors Slice's default ignore dirs and binary extension set, respects each root's `.gitignore`, and applies the `ignore` list from a root's `.ghostslice.json` profile when one exists, so the index sees the same project Slice sees.
- Token estimator: search results carry excerpt and whole-file token figures from Slice's calibrated estimator (same method stamp), loaded from an installed or sibling GhostSlice when reachable, with a documented fallback estimator when it is not. All counts labelled estimates.
- Output shape: excerpt hits name project root + relative path + line range, exactly the identifiers a follow-up `ghostslice slice` or `ghostverify pre` call needs.

Integration contract:
- Input: one or more project roots the user names explicitly on the command line. Nothing is indexed that was not named. No default home-directory crawl, ever.
- Index location: one sqlite database in the user's local state dir, `~/.local/state/ghostindex/index.db` by default (override with `--db` or `GHOSTINDEX_DB`). Project trees are never written to by indexing or searching.
- Output: ranked hits, each a bounded excerpt (merged windows around match lines), with per-hit and per-file token estimates, in text for humans and `--json` for agents.

## MVP (v0.1) - local CLI, sqlite FTS5, offline only
Rationale: same as Slice v0.1. CLI proves the index on real multi-project machines in days. An MCP server and a dashboard panel are later waves once result quality is trusted.

1. Build an index: `ghostindex index <root> [<root> ...]`
   - Walks each named root, skipping Slice's default ignore dirs, binary files, files over a size cap (default 2 MiB, configurable), and anything matched by the root's `.gitignore` or its `.ghostslice.json` ignore list.
   - Stores per file: root, relative path, sha256 of contents, size, mtime, language (Slice's extension map), line count, estimated tokens.
   - Full text goes into a sqlite FTS5 table (stdlib `sqlite3`), keyed to the file row. Nothing leaves the machine; there is no network code in the tool at all.

2. Incremental update: `ghostindex update [<root>]`
   - Re-walks named roots (or all indexed roots), compares size + mtime, then sha256. Only new or changed files are re-read and re-indexed; vanished files are removed from the index.
   - Reports exact counts: added, changed, removed, unchanged. An update with no changes must report all unchanged and touch no FTS rows.

3. Search: `ghostindex search "<terms>" [--root <path>] [--limit N] [--context N] [--max-tokens N] [--json]`
   - FTS5 MATCH query built from the user's terms (AND by default, `--any` for OR), ranked by FTS5 bm25.
   - Each hit returns bounded sliced excerpts, not the file: windows of +/- context lines (default 3) around match lines, overlapping windows merged, excerpts capped per hit and in total by estimated tokens.
   - Every hit shows root, relative path, line ranges, the excerpt text with match lines marked, excerpt token estimate, and whole-file token estimate, so the cost of pulling the full file is visible before anyone pays it.
   - Exit codes: 0 = matches found, 1 = no matches, 2 = could not search (no index, bad root filter, FTS5 unavailable). Never a silent empty success on a broken index.

4. Index housekeeping: `ghostindex list`, `ghostindex stats`, `ghostindex remove <root>`, `ghostindex doctor`
   - `list`: every indexed root with file counts, total estimated tokens, last update time, and the estimator method stamp in force.
   - `stats`: database path and size, total files, total tokens, per-root breakdown.
   - `remove`: drops one root's rows from the index. Never deletes anything from the project itself.
   - `doctor`: reports sqlite version, FTS5 availability, database path, and any indexed root that no longer exists on disk.

## Out of scope for v0.1
- Semantic or embedding search, LLM reranking, or query understanding. v0.1 is keyword full-text search with bm25 ranking, and says so.
- Indexing anything the user did not name: no home crawl, no watching yet (GhostWatch owns change signals), no editor or OS integration.
- Serving results to other machines, a shared team index, sync, accounts, telemetry. The index is one file on one machine.
- Slicing bundles, exporting context packs, or editing files. Hits point at files; Slice does the cutting.
- An MCP server (candidate for v0.2, same stdio discipline as Slice's, once the CLI result shape is stable).
- Indexing binary content, archives, or PDFs. Text-shaped files only, same as Slice's scanner.

## Build estimate
- Scanner + ignore handling (.gitignore, Slice defaults, profile ignores): 1-2 days
- sqlite schema + build + hash-based incremental update: 1-2 days
- Search + bm25 ranking + excerpt windowing + token budget: 1-2 days
- CLI (index / update / search / list / stats / remove / doctor): 1 day
- Tests (two-project fixture, planted unique terms, incremental counts, ignore proofs), README, demo indexing GhostSlice + GhostBus: 2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through. Excerpt quality (window merging and caps) is the part most likely to need a second pass; ranking is FTS5 bm25 and is not the risk.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: suite packaging and support. A hosted or shared index is explicitly not the plan; local and offline is the product promise. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Two-project fixture: index two small projects; a term unique to project B returns only project B's file, with an excerpt whose estimated tokens are smaller than the whole file's.
- Ranking: a file whose body is about the search term ranks above a file that mentions it once in passing, on a fixture built to show the difference.
- Incremental proof: modify one file, delete one file, add one file; `update` reports exactly 1 changed, 1 removed, 1 added, and the modified file's new text is searchable while its old unique term is gone.
- Ignore proof: terms planted only inside `node_modules`, a `.gitignore`d file, and a binary file never appear in any search result.
- Non-destructive proof: hashing every file in the fixture roots before and after `index`, `update`, and `search` shows zero changes; the database file exists only under the state dir (or the `--db` path given).
- Real-machine smoke: index GhostSlice's own repo plus one sibling project, search a known symbol, and the defining file appears in the top hits.

## Risks / honest notes
- The `.gitignore` matcher is a pragmatic subset (patterns, negations, directory rules, globs), not a full reimplementation of git's wildmatch. Edge cases may differ from git's own answer; the verification fixtures pin the common cases and the limit is stated, not hidden.
- bm25 ranks text relevance only. It knows nothing about code structure, so a heavily commented mention can outrank a terse definition. Excerpts show match lines so a human or agent can judge; structure-aware ranking is a later wave if it earns its place.
- FTS5 stores a full copy of indexed text inside the database file. The index of large project sets will be a real file on disk (doctor reports its size), and removing a root is the supported way to reclaim it.
- Token figures are Slice estimator estimates, labelled as such everywhere they print. They are budgeting aids, not tokenizer truth.

## Next gate
Ryan's go on: (1) GhostIndex as working name, (2) state-dir database as the default index location with `--db` override, (3) keyword FTS5 search only in v0.1, semantic search explicitly deferred, (4) build order: Index is #26 of the suite, Wave 4.
