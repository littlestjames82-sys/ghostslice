# GhostDocs - GhostSlice for Non-Code Corpora
Working name, prepared Oct 14, 2026. Paired tool #12 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostDocs: the plainest name in the suite, aimed at non-developer buyers who will not decode a clever one. It slices documents the way GhostSlice slices code.
- Naming caution recorded: Docs is a crowded word (documentation platforms, Google Docs associations). The build gate name check must specifically test confusion with document editors, because this tool edits nothing, it selects and exports.
- Reserve alternative: GhostCorpus (accurate for the RAG use, but jargon for the local-business buyer this tool is meant to reach).
- Treat as a working name until that check runs, same discipline as GhostSlice Oct 12.

## The problem
The token problem is not only a code problem. A support agent, a chatbot, or a new hire fed a company's whole knowledge base (help centre exports, policy manuals, SOPs, product docs, years of PDFs) gets the same failure as an agent fed a whole repo:
- Most of the corpus is irrelevant to any one question, much of it is duplicated or superseded, and nobody can see the cost or the shape before it is fed in.
- Unlike code there is no AST, but there is structure: headings, sections, versions, dates, and near-duplicate pages that were edited instead of replaced.

The buyers here are different from Slice's: support leads, operations managers, and local businesses of the kind Ryan already serves (the After Hours answering-service world, studio website clients). They do not need a developer tool, they need their own documents made agent-ready, measurably, without handing the corpus to a cloud service to do it.

## How this differs from GhostRecall (read this before building either)
Recall and Docs both slice non-code text, so the boundary is written down:
- **GhostRecall**: a *software project's* memory (decisions, ADRs, git history, project rules) for *coding agents*, merged into a Slice bundle. Project-local by rule, provenance per decision, superseded-decision handling.
- **GhostDocs**: a *business or product corpus* (help centre, manuals, SOPs, policies) for *support / general agents and RAG pipelines*, exported in retrieval-ready chunks, with its own buyer and its own export targets.
Shared engine, different corpora, different users, different exports. If a real project ever fits both descriptions, the user picks by audience, and the plans do not merge the tools to solve that overlap.

## Position in the Ghost stack
- GhostSlice governs what a coding agent reads about code.
- GhostDocs governs what a support/general agent reads about a business or product.
- It is the suite's only deliberate step outside the developer buyer. That is its upside and its focus risk, stated up front: it should be built when a real corpus and a real buyer are on the table (a client engagement, the After Hours line of work), not as a speculative platform.
- It does not answer questions itself. Like Slice, it prepares context. Answering belongs to whatever agent or RAG system consumes the export, governed by Seatbelt where actions are involved.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Scanner + ignores + token estimator + prices: a corpus gets the same cost view as a repo (total estimated tokens, heat by document/section), same estimator stamp, same local dated price table, estimates labelled.
- Markdown `headings` mode and notebook-style structural slicing generalise into section modes for documents: full, headings+first-paragraph, section-selected, exclude. PDF and DOCX text extraction is the new, corpus-specific work (see MVP for format scope and honesty limits).
- Duplicates: Slice exact (sha256) + near-duplicate (line-shingle Jaccard) detection is directly reusable and is arguably the headline feature here: superseded and copy-pasted policy pages are the corpus equivalent of dead code.
- Task selection (TF-IDF): given a question or a ticket topic, select the sections that belong in context, with the same TF-IDF method as `ghostslice task`, no embeddings in v0.1.
- Manifest + check + history: a Docs export is a manifest-backed bundle that validates the Slice way, so a corpus export is reproducible and auditable (which version of which page went into the agent's context on a given date).
- Secrets / sensitive guard: the Slice guard patterns plus corpus-specific cautions (personal data shapes in support docs) run before export, findings redacted as path + line + type only, and flagged documents are held out by default. Support corpora hold real customer text more often than repos do, this step is a gate, not a report.

## MVP (v0.1) - corpus scan, dedupe, section slice, two exports
1. Ingest + scan: `ghostdocs scan <corpus-folder>`
   - Formats in v0.1: Markdown, plain text, HTML (text extracted, scripts/styles stripped), PDF (text layer only). DOCX and scanned/image PDFs are explicitly not covered in v0.1 and the scan names any it finds as not covered, it does not silently skip them.
   - Per-document and per-section token heat, duplicate clusters (exact + near, with the cluster's newest dated member marked as the probable current one, labelled a heuristic), stale flags where a document carries an older date than a near-duplicate sibling.

2. Corpus profile: `.ghostdocs.json` in the corpus folder
   - Includes/excludes, authoritative sources (a folder whose version wins duplicate conflicts for export), per-source modes, the user's retention choice for superseded material (exclude from exports but keep in reports by default).
   - Separate filename from `.ghostslice.json` on purpose: a corpus is not a code project and the tools should not fight over one file if a folder ever holds both.

3. Selection + export: `ghostdocs export <corpus> --task "..." -o <folder>` and full-corpus mode
   - Two export shapes only in v0.1:
     - Agent bundle: Slice-style bundle (PROMPT.md + files + manifest) of selected sections for direct agent context.
     - Chunk pack: JSONL of chunks (one per section, with source path, heading trail, date, sha256, token estimate) sized for a RAG importer to consume, chunk boundaries are document sections, not arbitrary splits, and the pack documents that choice.
   - `--fit <tokens>` uses the same downgrade discipline as Slice (headings mode before exclude, authoritative sources protected), unfittable writes the bundle and exits 1.

4. Corpus report: `ghostdocs report <corpus>`
   - Single-file HTML in the Slice report style, offline: heat map of the corpus, duplicate clusters with token waste totals, stale list, not-covered list, and the estimated saving of exporting deduped vs raw. Written for a non-developer reader in plain words, technical appendix second.

## Out of scope for v0.1
- Answering questions, a chat UI, a hosted knowledge base, embeddings/vector search, or any model call.
- OCR, DOCX, spreadsheet or slide content, auto-translation, or rewriting/summarising documents with a model. Modes are extractive only, like Recall.
- Editing source documents, deleting duplicates from the corpus, or syncing with help-centre platforms (Zendesk/Intercom etc). Platform connectors are per-platform later gates with their own credentials, not v0.1 scope.
- Handling a corpus the user has no right to process. The tool is local, the responsibility note goes in the README plainly.

## Build estimate
- Text extraction (MD/TXT/HTML/PDF text layer) + section model: 4-5 days (PDF variance is the honest risk)
- Corpus scan (heat, duplicates, stale heuristics) + profile: 3 days
- Selection + both exports + fit + report: 3-4 days
- Tests (duplicate-cluster fixture with a superseded page, a text-layer PDF fixture, a no-text PDF that must land on the not-covered list, a planted personal-data fixture that must be held out), README, demo on a real document set: 2-3 days
Total: roughly 2 to 3 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- Core CLI free under the house MIT pattern is the default assumption, but this is the one companion where a studio-service model (corpus cleanup + agent-ready export as a client engagement) may fit better than a software launch. That fork is Ryan's explicit decision at the build gate, it is not pre-decided here, and no pricing is set either way.

## Verification bar
- Dedupe test: a fixture corpus with one exact duplicate and one edited near-duplicate (newer date) clusters both, marks the newer as probable current, and the deduped export contains it once.
- Coverage honesty test: a fixture image-only PDF appears on the not-covered list in scan, report, and any export attempted from that corpus. It appears in no bundle.
- Hold-out test: a fixture document with a planted personal-data shape is excluded from a default export and named (path + type only) in the report.
- Reproduction test: chunk pack totals equal manifest totals, chunk hashes verify, and re-running export on an unchanged corpus reproduces identical totals.

## Risks / honest notes
- PDF text extraction in stdlib is limited and messy on real-world files (columns, tables, broken encodings). v0.1 must show extraction quality per document (characters extracted vs pages, a low-yield flag) rather than pretending every PDF worked. If real corpora defeat stdlib extraction, the honest move is a format-scope cut for v0.1, stated to Ryan, not a silent dependency adoption that breaks the house stdlib rule without his say.
- "Probable current" duplicate calls can be wrong, and in policy/SOP corpora picking the wrong version has real consequences. Exports default to newest-by-date with the cluster shown in the report; authoritative-source pinning exists so a human can overrule the heuristic per folder.
- This tool can drift into generic document AI, a crowded and capital-heavy niche. The v0.1 edge is the same as Slice's: local, measurable, manifest-backed, no corpus leaving the machine. Keep the scope there.

## Next gate
Ryan's go on: (1) GhostDocs as working name, pending the editor-confusion check, (2) first real corpus and buyer to build against (client / After Hours adjacent / demo corpus), including the free-tool vs studio-service fork, (3) format scope MD/TXT/HTML/PDF-text-layer only in v0.1, (4) build slot: Docs is #12 in the suite, last by design, demand-driven.
