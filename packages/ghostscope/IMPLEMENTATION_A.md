# GhostScope v0.1 - Implementation Record (Agent A, core)

Built Oct 14, 2026 from ~/workspace/ghostscope/PLAN.md. Python
stdlib only, local git only, no hosting API, no model calls, no
push/publish/spend. Agent A file ownership respected: only
`src/**`, `pyproject.toml`, and this file were written by A.
(tests/, README.md, examples/ belong to Agent B; B's suite was run
against this core as a cross-check, see below.)

## Layout

```
pyproject.toml                 ghostscope 0.1.0, zero dependencies, console script
src/ghostscope/
  __init__.py / __main__.py    version 0.1.0
  tokens.py        GhostSlice-compatible token estimator (see below)
  scanner.py       .gitignore-aware walk, binary skip, language/test/lockfile
                   flags, generated/minified/vendored detection + evidence
  profile.py       `scope` section of .ghostslice.json (sensitive_paths,
                   entry_points); unknown scope keys fail loudly
  outline.py       symbol outlines: Python stdlib ast (exact), other
                   languages parser-lite regex (always labelled)
  slicer.py        modes full/signatures/interfaces/strip-tests/exclude/
                   headings (Python ast spans; brace-lite for other languages;
                   markdown headings mode)
  diffparse.py     unified diff parser (status, hunks, added/deleted lines
                   with new/old line numbers, renames, binary marks)
  gitinput.py      change input: --base/--head range, --staged, --diff file;
                   diff verification (see below)
  graphbuild.py    import + call graph, undirected distance BFS (cap 2 for
                   pack inclusion), symbol callers, transitive callers
                   capped at depth 3 (cap recorded in scope.json),
                   covering-tests mapping with per-file method labels
  secretslite.py   secret-shaped added-line detection (type + line only,
                   values never stored or printed)
  pack.py          analysis (changed symbols, risk, notes), pack export,
                   REVIEW.md rendering, explain
  validate.py      pack check mirroring `ghostslice check` semantics
  mcp_server.py    stdio JSON-RPC MCP: scope_pack, scope_explain, capped
  cli.py           pack / explain / check / mcp commands
```

## Key design decisions

1. **GhostSlice validation compatibility.** A pack is manifest.json +
   PROMPT.md + files/ + scope.json + REVIEW.md. `tokens.py` reproduces
   GhostSlice v1.0.6's estimator exactly (BPE-like split v2, per-language
   calibrated factors, minified-JS family), and manifest entries carry the
   same fields (path/mode/language/package/original_tokens/sliced_tokens/
   sha256, totals, token_method string). Verified live: GhostSlice's own
   `ghostslice check` returned ok:true on a GhostScope pack (below).
   No context.json/context.xml is written, so GhostSlice's wrapper
   validation is not triggered.
2. **Diff verification.** A parsed diff must match the state it claims:
   range input is checked hunk-by-hunk against the blob at `head`,
   staged against the index blob, a bare diff file against the working
   tree. Mismatch = exit 2 naming file + hunk. `--no-verify-diff` exists
   as an explicit opt-out.
3. **Modes by graph distance.** Changed files full (deleted files are
   `exclude` manifest rows with base-side original tokens), distance-1
   neighbours signatures, distance-2 interfaces, covering tests full,
   markdown neighbours headings. `--fit` downgrades distance-2 then
   distance-1 neighbours only; changed files and covering tests are
   never downgraded; if the budget still cannot be met the pack is
   written and the CLI exits 1 (Slice `--fit` discipline), with the
   fit report in manifest.json and scope.json.
4. **Risk is reasons, then a score.** Per changed symbol: direct callers
   (production only, see 5), transitive callers within 3 hops, exported
   API (__all__/export lists, or a top-level public symbol of a module
   imported by others), entry point (profile entry point or __main__
   guard file), no covering test, signature changed, symbol removed,
   sensitive path from the profile `scope` section (no built-in path
   guesses), secret-shaped line added. File-level secret/sensitive
   signals also surface when no symbol was mapped (e.g. a JSON file).
   REVIEW.md lists reasons next to every score.
5. **Caller count semantics.** `caller_count` counts non-test direct
   callers; test-file callers are reported separately as
   `test_callers`, and `all_direct_callers` keeps the full list.
   A covering test calling a symbol is cover, not blast radius.
6. **Factual notes only.** signature-changed (old vs new signature
   quoted), symbol-removed, caller-not-updated (for signature/removed
   symbols, production callers not in the diff), no-covering-test,
   test-deleted. Each note cites file + symbol. No approve/request-
   changes/comment surface exists anywhere in the code.
7. **Covering tests.** Python: AST-verified (test file imports the
   changed module or calls a changed symbol). Other languages:
   import/name heuristic, labelled `parser-lite heuristic
   (name/import based)` in scope.json, REVIEW.md, and MCP output.

## Smoke tests (fixtures built in /tmp, git repos, run Oct 14, 2026)

Fixture 1, Python blast radius + sensitivity (lib.compute called by
caller1-5 + a test; isolated.py with 200 generated lines; auth_notes.py
pinned sensitive in profile):
- `ghostscope pack --base HEAD~1 --head HEAD` exit 0. Reading order:
  1. lib.py [full] risk 50 "6 callers; exported API" (at that run the
  count still included the test caller; after fix 5 it reports the
  production count), 2. auth_notes.py risk 40 (no covering test +
  sensitive path), 3. isolated.py risk 20 (no covering test).
  All 5 caller modules packed at signatures (distance 1), the
  covering test packed full.
- `ghostslice check` (from ~/workspace/ghostslice, PYTHONPATH=src) on
  the pack: `ok: true, errors: [], files_checked: 10,
  total_sliced_tokens: 1311`. GhostScope's own `check`: OK.
- REVIEW.md states "No covering tests found for this file" in plain
  words for isolated.py and auth_notes.py.

Fixture 2, signature change + deleted covering test + planted secrets
(AKIA-shaped key in a new file, ghp_-shaped token appended):
- Notes produced verbatim kinds: signature-changed (old/new signatures
  quoted), caller-not-updated naming caller1.py:run1 ... caller5.py:run5,
  no-covering-test, symbol-removed (test_compute), test-deleted.
- lib.py risk 80 (5 callers, exported API, no covering test, signature
  changed). Both secret files risk 45 with reason "secret-shaped line
  added"; secret values appear nowhere in scope.json/REVIEW.md
  (findings are line + type only).

Fixture 3, fit / staged / diff-file discipline:
- `--fit 200` on a 1327-token pack: neighbours downgraded
  signatures -> interfaces -> exclude, changed files stayed full,
  after = 1262, fit.ok false, CLI exit 1, pack written.
- `--staged` packed exactly the staged lib.py change.
- A stale diff file (diff captured, then worktree reverted) was
  REFUSED: "diff mismatch: lib.py hunk 1 (@@ -3 +3) does not match the
  content it claims to describe", exit 2. The same diff with the change
  present in the worktree packed correctly, mapping the change to
  symbol `helper`.
- Bad profile (typo'd scope key) refused loudly, exit 2. Empty staged
  input refused ("no file changes"), exit 2.

Fixture 4, TypeScript (parser-lite honesty):
- api.ts change mapped by parser-lite, totalArea callers = 2,
  app.ts packed at signatures (distance 1), api.test.ts identified as
  covering with method labelled "parser-lite heuristic (name/import
  based)". Known wart (recorded, not hidden): the lite outliner
  attributed totalArea as `Shape.totalArea` because the preceding
  interface line opens a brace block. Caller/test mapping was still
  correct.

MCP: initialize/tools-list/tools-call round trip over stdio verified.
Tools listed: scope_pack, scope_explain. scope_explain on caller1.py
returned in_pack=true, mode signatures, distance 1. Unknown tools
and bad arguments return JSON-RPC errors, the server does not crash.

Install: `pip install .` in a fresh venv succeeded; the installed
`ghostscope --version` prints 0.1.0 and `ghostscope check` validated
the fixture pack. `python3 -m compileall src` clean.

Cross-check with Agent B's suite (tests/ written independently):
initial run 23 passed, 1 skipped, 1 failed
(test_caller_count_is_the_stated_reason, which expects the fixture's
6 production callers as the stated count). That failure drove design
fix 5 above. Final run: **24 passed, 1 skipped** (skip =
optional `ghostslice` on PATH cross-check, which A verified manually
instead, see fixture 1).

## Honest limits

- Parser-lite outlines for non-Python languages are line-regex:
  nested declarations can be mis-attributed (fixture 4), and
  signatures/interfaces slicing for those languages is
  declaration-line based, not AST based.
- Symbol call resolution is name-based after same-file/imported
  checks; ambiguous project-wide names are counted as unresolved,
  not guessed.
- Python signature slicing for a changed symbol relies on a symbol's
  AST line span: a change touching only a decorator or a multi-line
  signature edge can map to the module pseudo-symbol.
- Stale-caller notes use production direct callers only.
- The pack manifest lists packed files only (not the whole repo);
  repo totals live in scope.json/REVIEW.md as estimates.
