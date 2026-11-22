# GhostPrimer v0.1 - Agent A implementation record
Built Oct 14, 2026. Ownership: PLAN.md, src/**, pyproject.toml, this file.
tests/**, README.md, examples/** are Agent B's and were not touched.

## Delivered
- PLAN.md in GhostSlice format (why this name, problem, position in the
  Ghost stack, hard rules, MVP, out of scope, build estimate, pricing
  draft marked not public and not decided, verification bar, risks,
  next gate). No em dashes.
- src/ghostprimer/:
  - scan.py: project facts (pyproject.toml via tomllib, package.json),
    entry-point detection (script targets, package mains, conventional
    entry file names, shallow package __init__ files), language mix,
    top-level layout, Python fan-in via ast with relative-import
    resolution, and the locality guard: assert_project_local refuses
    sources outside the project root and refuses the user's private
    memory locations (~/MEMORY.md, ~/memory/) by resolved path before
    anything is read.
  - slicer.py: modes full / signatures / outline / head. Python exact
    via ast (imports, signatures, docstring first lines, class methods,
    module constants). JS/TS parser-lite regex, labelled. Other
    languages head excerpt, labelled. Confidence recorded per file.
  - memory.py: two paths, recorded in the manifest as memory_path.
    recall-bundle consumes a GhostRecall bundle's current memory items
    verbatim (superseded / excluded / blocked never included, Recall's
    provenance kept). fallback is a shallow pass over AGENTS.md,
    CLAUDE.md, DECISIONS.md, docs/decisions/*.md, CHANGELOG.md (latest
    entry only), CONTRIBUTING.md, PLAN.md, ROADMAP files: headings plus
    capped section extracts, file + line provenance per item. Secret-
    shaped literals block the item (file-level in the fallback path),
    values never recorded. README extract = headings + first paragraph
    per heading.
  - tokens.py: delegates to GhostSlice's calibrated estimator (package,
    $GHOSTPRIMER_GHOSTSLICE_SRC, or sibling checkout) so totals
    reproduce under `ghostslice check`; documented chars/4 fallback
    with its own method string when Slice is absent.
  - bundle.py: build + check. Manifest follows the GhostSlice bundle
    schema (per-file original_tokens / sliced_tokens / sha256, top-level
    integer totals, token_method) plus primer fields (facts,
    entry_points, memory_items with provenance, memory_blocked,
    not_included, primer_sha256, budget_unmet, memory_path, template
    text list). Budget: default 6,000 estimated tokens, memory capped
    at 40 percent, downgrade ladder signatures -> outline -> exclude,
    entry points never dropped below outline (budget reported unmet
    instead). check recomputes hashes and totals, verifies PRIMER.md
    against primer_sha256, and re-verifies that every memory item's
    provenance resolves inside the recorded project root and not into
    a private memory location. Exit codes 0 / 1 / 2.
  - doctor.py: read-only source inventory (facts, entry points, which
    memory files exist, estimator in use, recall bundle detection).
  - mcp_server.py: stdio JSON-RPC, primer_build / primer_check, capped
    summary payloads, no file bodies.
  - cli.py: build | check | doctor | mcp. pyproject.toml: ghostprimer
    0.1.0, zero dependencies, console script.

## Verification (all run by Agent A on the built core)
Fixture project (/tmp, python src-layout widget package with a called
core module, an orphan module, DECISIONS.md, two-entry CHANGELOG.md):
- build: 211 original -> 143 sliced tokens, 4 files, memory via
  fallback. Entry points src/widget/__init__.py and src/widget/cli.py
  at signatures; core.py fan_in 2 (imported by both).
- ghostprimer check: exit 0, ok true, totals reproduced.
- GhostSlice cross-check: `ghostslice check` on the Primer bundle:
  ok true, errors [], files_checked 4, totals 143 / 211 reproduced.
- Tamper: one appended line to PRIMER.md -> check exit 1, sha256
  mismatch named.
- Secret: planted AKIA-shaped key appended to DECISIONS.md -> the file
  is blocked (types named, value never printed), 0 occurrences of the
  literal in PRIMER.md, remaining memory items still primed.
- Recall consumption: hand-built Recall bundle fixture with one active
  and one superseded decision -> current item text in PRIMER.md (1
  hit), superseded text absent (0 hits), manifest memory_path is
  recall-bundle.
- Exclusion: assert_project_local refuses ~/MEMORY.md with the
  private-memory reason and /etc/hostname with the outside-root
  reason, before any read.
- Budget: --budget 30 -> bundle still written, budget_unmet true,
  entry points kept at outline, other files recorded in not_included
  with "code budget spent".
- CHANGELOG: latest entry (0.2.0, Added Spinner class) present, older
  entry text absent.
- Doctor on the fixture: facts, both entry points, source inventory
  correct; estimator reported as GhostSlice's v2 method.
- MCP: initialize, tools/list, tools/call primer_check all answered
  correctly over stdio.
- Real project smoke: built a primer for GhostSlice itself
  (113,220 original -> 4,612 sliced tokens inside the default budget,
  1,387 memory tokens via fallback) and that bundle also passes
  `ghostslice check` ok true.
- Install: pip install verified from a /tmp copy of the tree with a
  stub README (the real README.md is Agent B's file and does not exist
  yet, and pyproject references it); installed CLI reports 0.1.0 and
  checks a bundle. Installing from the live tree will work once
  Agent B's README lands.
- Stdlib audit: imports across src/** are stdlib only (ast, argparse,
  hashlib, json, os, re, sys, tomllib, datetime, pathlib) plus
  intra-package imports and the optional ghostslice estimator import.
  No network code, no subprocess.

## Bugs caught and fixed during verification
1. Fan-in ignored relative imports (`from .core import ...`), so the
   most-imported module ranked 0. Fixed by resolving ImportFrom levels
   against the importer's package, and by registering src-layout
   dotted names without the src. prefix in the module map.
2. CHANGELOG latest-entry logic treated the document title heading as
   the first release section and dropped the actual latest entry.
   Fixed: preamble plus first release section only.
3. Heading-only memory sections produced empty items duplicating the
   section heading. Fixed: sections with no extractable body lines are
   skipped.

## Known limits (honest)
- The fallback memory path blocks at file level: one secret-shaped
  literal blocks the whole memory file, not just the section. The
  Recall-bundle path blocks per item, since Recall already split items.
- The memory cap always keeps at least one memory item, so an
  impossibly small budget can still be exceeded by memory alone; the
  bundle reports budget_unmet rather than silently dropping all memory.
- Test files (tests/, test/) are excluded from the starter slice by
  path prefix only; a test file living in src/ would be treated as code.
- Fan-in counts Python imports only. JS/TS files rank by entry-point
  status then path order; their fan_in is recorded as 0.
- Entry-point detection is heuristic (script targets + conventional
  names + shallow __init__ files). A project whose entry point has an
  unusual name and no script metadata will prime without it, and the
  start-here list will say no entry points detected only when the list
  is fully empty.
- Non-Python slicing is parser-lite or head excerpt and is labelled as
  such in the manifest; nested JS/TS declarations can be missed.
- If GhostSlice is not importable, bundles are built on the chars/4
  fallback estimator and will NOT reproduce under `ghostslice check`;
  the manifest token_method says which estimator was used.
- pip install . from the live tree was not run because README.md is
  Agent B's file and has not landed yet (verified from a copy instead,
  see above).

## Gates held
Python stdlib only, local only, no network, no GitHub push, no PyPI /
publish, no announcements, no spend. Project-local sources only, with
the private-memory exclusion enforced by path check in code.

## Polish round addendum (Oct 14, 2026)
Three statements above were stale by the time of the polish round and
are corrected here rather than rewritten in place (see POLISH_REPORT.md
for the full record):
- "Fan-in counts Python imports only. JS/TS files rank by entry-point
  status then path order; their fan_in is recorded as 0." Superseded:
  JS/TS now get a parser-lite import graph (scan.js_fan_in) and rank
  by real fan-in; every manifest file entry also records
  fan_in_method ("ast" / "parser-lite" / "none").
- "The fallback memory path blocks at file level" (Delivered section
  and Known limits). Superseded by the D1 fix round: the fallback path
  blocks per item, recorded in FIX_REPORT.md.
- "pip install . from the live tree was not run because README.md is
  Agent B's file and has not landed yet." README.md has landed; the
  polish round installed ghostprimer 0.1.0 from a copy of the current
  tree and the installed console script runs.
