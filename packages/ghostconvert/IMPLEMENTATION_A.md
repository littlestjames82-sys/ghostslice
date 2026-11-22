# GhostConvert v0.1 - Agent A implementation record
Built Oct 14, 2026. Ownership: PLAN.md, src/**, pyproject.toml, this file.
tests/**, README.md, examples/** belong to Agent B and were not touched.

## What was built
- `PLAN.md` - written first, in the GhostVerify plan format (why this name,
  problem, position in the Ghost stack, pairing contract, MVP, out of scope,
  build estimate, pricing draft marked not public and not decided,
  verification bar, risks, next gate). No em dashes (grep count 0).
- `pyproject.toml` - ghostconvert 0.1.0, zero dependencies, console script
  `ghostconvert`.
- `src/ghostconvert/bundle.py` - bundle reader. manifest.json is the
  authority for file order, modes, language, token estimates, sha256. Bodies
  come from files/<path> exactly as GhostSlice wrote them; PROMPT.md is the
  fallback, parsed on its `# File: <path> (mode: <label>)` headers. Manifest
  paths are validated relative and contained inside the bundle; an escaping
  path is skipped and recorded, never followed. Malformed manifest or a
  bundle with zero readable bodies raises BundleError (CLI exit 2).
- `src/ghostconvert/convert.py` - four renderers + losses accounting.
  - agents: one AGENTS.md, `## File: <path> (mode: <label>)` sections,
    fenced bodies, manifest order.
  - copilot: one .github/copilot-instructions.md, same section discipline.
  - generic: one prompt.md, `# File:` headers mirroring PROMPT.md shape.
  - cursor: .cursor/rules/ghostconvert-<group>.mdc per top-level directory
    group (root-level files in a `root` group), frontmatter with description,
    globs naming the original paths, alwaysApply: false; per-file sections
    keep mode labels.
  - Fences are lengthened past the longest backtick run in a body, so a
    body containing ``` cannot break its block.
  - Mode labels match GhostSlice's own PROMPT.md labels, including
    `symbols: a, b` expanded from symbols_included.
  - Losses are computed from the manifest per target and written to
    LOSSES.md in the output dir: excluded files (with mode reasons),
    per-file sha256 hashes, per-file token estimates, redaction metadata,
    slice scores/fit metadata, mode reasons, package grouping, source
    encodings, files with no readable body, bundle-escaping paths, plus
    target-specific losses (Cursor regrouping and generated frontmatter;
    agents/copilot have no machine-readable per-file metadata channel).
    A zero-loss conversion would say so explicitly in the note.
- `src/ghostconvert/cli.py` - `convert <bundle> --to agents|cursor|copilot|
  generic|all -o <outdir> [--force]`, `inspect <bundle>`, `targets`.
  Exit codes: 0 done (losses are named, not failures), 2 bad bundle or
  arguments. Guards: output dir must not be the bundle dir or inside it;
  artifacts that already exist are refused without --force, and a refused
  run writes nothing.

## Smoke results (all run by Agent A against real GhostSlice output)
1. Fixture bundle built by GhostSlice itself (`ghostslice export` on a
   4-file fixture): modes signatures / strip-tests / exclude / full.
   `inspect` reported all four modes and totals (63 sliced of 120).
   `convert --to all` wrote AGENTS.md, .github/copilot-instructions.md,
   prompt.md, 2 cursor .mdc files, and a LOSSES.md per target. Loss counts:
   agents 5, copilot 5, cursor 5, generic 4 (excluded file, hashes, per-file
   tokens, missing body, plus the target-specific loss where applicable).
   sha256 of every bundle file identical before and after; no new file
   inside the bundle.
2. The fixture's strip-tests file has an empty slice, so GhostSlice ships
   no body for it anywhere (not in files/, not in PROMPT.md). Convert names
   it under "Files with no readable body" in every LOSSES.md rather than
   inventing content. This is the honest behaviour and matches what the
   receiving agent would (not) get from the original bundle either.
3. Synthetic bundle (hand-written manifest): a file present only in
   PROMPT.md converted through the fallback path with its body intact; a
   symbols-mode file rendered its header as `symbols: run, Pair.swap`; a
   `../../evil.py` manifest path was skipped, unfollowed, and named in
   LOSSES.md under "Manifest paths outside the bundle".
4. Real-repo bundle: `ghostslice export` of the GhostVerify tree (42
   non-excluded manifest entries, 26 with shipped bodies) converted to all
   four targets with no error; AGENTS.md section order equals manifest
   order (verified programmatically), source bundle byte-identical after.
   The 16 body-less entries are empty slices (mostly stripped tests) and
   are named in LOSSES.md.
5. Guards verified: output inside bundle -> exit 2; overwrite without
   --force -> exit 2 with nothing written; with --force -> exit 0;
   malformed manifest JSON -> exit 2 with the parse error named.
6. Packaging: installed from a /tmp copy with
   `pip install --no-build-isolation --target`, console script reports
   `ghostconvert 0.1.0`. The copy carried a stub README because Agent B's
   README.md had not landed yet; pyproject's `readme = "README.md"` is the
   suite-standard field and the real install completes once B lands it.
7. Stdlib audit: no urllib / http.client / socket / requests / subprocess
   tokens anywhere under src/. No GhostSlice code is imported; Convert
   reads the documented bundle format only.

## Known limits
- Cursor grouping by top-level directory is a judgement call and is named
  as a loss; global manifest interleaving across groups is not preserved.
- Bodies are decoded as UTF-8 with replacement on error (the bundle ships
  UTF-8 text; a non-UTF-8 source_encoding is named in losses).
- PROMPT.md fallback bodies are rstripped, matching how Slice renders
  them; byte-exactness is guaranteed only for the files/ source, which is
  the primary path.
- Empty-slice files (sliced_tokens 0, no body shipped by Slice) can only
  be named, not converted. There is nothing to convert.
- No MCP server, no reverse conversion, no in-place merge into a live
  project, per the plan's out-of-scope list.

## Gates held
Stdlib only, local only, no network, no GitHub push, no PyPI/publish,
no announcements, no spend. Source bundles were never modified.
