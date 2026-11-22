# GhostPrimer seam fix report (ecosystem pass, Oct 14, 2026)

Fix round for the two cross-suite seams recorded in
`~/workspace/ghostslice-companions/ECOSYSTEM.md` (Seams #1 and #7),
both parent-verified before dispatch. Sole folder ownership for this
round. No version bump (pyproject still 0.1.0), stdlib only, local
only, no push, no PyPI/publish, no announcements, no spend.

## Test counts

```
PYTHONPATH=src python3 -m pytest tests -q
Before: 36 passed, 0 failed   (baseline, run before editing)
After:  43 passed, 0 failed   (36 pre-existing, untouched, + 7 new)
```

No existing test was edited, weakened, or deleted. New tests are all
in `tests/test_seam_fixes.py` and are black-box through the CLI.

## Seam 1: AWS shape aligned to canonical, whole list audited

Primer's blocking scan decides what may enter PRIMER.md, so its
`aws-access-key` pattern being AKIA-only was a live leak path for
ASIA temporary session keys. The pattern now matches GhostSlice's
canonical scanner (`ghostslice/secrets_scan.py`) exactly:
`\b(?:AKIA|ASIA)[0-9A-Z]{16}\b`.

Audit of the rest of Primer's shape list against canonical:

| Shape | Disposition |
|---|---|
| aws-access-key | **Changed**: AKIA-only -> `(?:AKIA\|ASIA)`. |
| github-token | **Changed**: token suffix now allows `_` (`[A-Za-z0-9_]{20,}`), matching canonical; the old class silently missed underscore-bearing tokens. |
| private-key | **Changed**: header variants now include DSA and PGP (`(?:RSA \|EC \|OPENSSH \|DSA \|PGP )?`), matching canonical; the finding type was renamed `private-key-block` -> `private-key` to match canonical naming. |
| openai-or-anthropic-key | Already identical to canonical. No change. |
| slack-token | Already identical to canonical. No change. |
| password-in-url | **Added**: a canonical detection-core shape Primer lacked entirely. |
| aws-secret-key | Not added as a bare pattern, deliberately: in canonical it is context-gated (a bare 40-char value counts only on a line naming an AWS secret), because the bare shape matches ordinary hashes. Primer's labelled `generic-api-key` assignment guard covers the labelled form. |
| sensitive-assignment / high-entropy-assignment | Not ported: in canonical these are assignment parsing with placeholder, entropy, and file-type gates, not standalone shapes. Primer retains its stricter labelled `generic-api-key` guard. |
| redacted-credential-marker, jwt, generic-api-key | Primer-specific extras, retained: the redaction marker is load-bearing for the D1 fix (see FIX_REPORT.md), and the other two only ever block more, never less. |

Probe of the aligned scanner (types only, values never printed):
ASIA and AKIA canaries -> `aws-access-key`; underscore-bearing
GitHub token -> `github-token`; DSA and PGP headers ->
`private-key`; credential-bearing URL -> `password-in-url`; Slack
token -> `slack-token`.

Regression tests (Seam 1):

- `test_asia_key_in_memory_blocks_the_item`: an ASIA canary in a
  copied fixture project's AGENTS.md blocks exactly that memory item
  (recorded in `memory_blocked` with shape name only); the canary
  appears nowhere in the bundle or CLI output, and the clean items
  from the same file are still included.
- `test_asia_key_in_code_excludes_the_file`: the same canary in the
  fixture's highest fan-in code file excludes the file from the slice
  and from `files/`, named in `not_included` with the
  `aws-access-key` reason; the canary appears nowhere in the bundle.

## Seam 2: Primer consumes a GhostHandoff pack (session loop closed)

Primer can now open session N+1 from session N's closing pack.

- New input: `ghostprimer build --handoff-pack <path>`, where the
  path is either a pack directory containing `handoff.json` or the
  `handoff.json` file itself. Also exposed as the `handoff_pack`
  argument of the MCP `primer_build` tool and as the `handoff_pack`
  parameter of `build_bundle`. Opt-in only: with no flag, bundles
  contain no handoff section and no `handoff_input` manifest key,
  and the render path is unchanged.
- New module `src/ghostprimer/handoff.py` reads the pack and derives
  exactly three items from its recorded facts: **Previous session
  state** (generation time, project, session window, branch/HEAD,
  working-tree and stash counts, upstream position, commits/files in
  window, latest commit, verification report summaries, marker
  counts), **Previous session open loops** (each loop's kind, detail,
  and source), and **Previous session next steps** (each step's text
  and source). Nothing is invented: empty loop/step lists render as
  the recorded fact that none were recorded.
- Safety: each handoff item passes through the same
  `secrets.scan_text` as project memory before it can be included. A
  flagged item is blocked per item (the other handoff items still
  carry forward) and recorded in `memory_blocked` with the pack's
  `handoff.json` path and shape names only, never the value.
- Validation: a missing/unreadable/invalid pack, a pack whose `tool`
  is not GhostHandoff, a pack naming a different project path, and a
  pack resolving into the assistant's private memory locations are
  all refused with a named error (CLI exit 2, the existing path for
  bad build inputs).
- Budget discipline: handoff items enter the existing memory pool
  and compete for the same 40 percent memory share
  (`MEMORY_SHARE`) as Recall/fallback items; they are considered
  first because the caller explicitly opted into carrying the
  session forward. Kept handoff tokens count inside
  `memory_tokens_estimate`, so the code slice's budget shrinks by
  exactly what the handoff spent. Items that do not fit are recorded
  in `not_included` with the existing "memory budget share spent"
  reason.
- Rendering and manifest: kept handoff items render in their own
  section, `## Previous session handoff (source: GhostHandoff pack)`,
  ahead of the project memory primer, each with `handoff.json:1`
  provenance. The manifest records the source as `handoff_input`:
  the supplied input path, input kind (directory/file), resolved
  `json_path` and `pack_dir`, tool, version, generation time, the
  project the pack describes, and items considered / included /
  blocked with their estimated tokens. `ghostprimer check` passes
  on handoff-fed bundles (covered by test and by the demo below).

Regression tests (Seam 2):

- `test_handoff_pack_directory_feeds_the_next_primer`: state facts,
  the open-loop detail, and the next step all appear in PRIMER.md;
  `handoff_input` names the pack directory and its `handoff.json`;
  all three items are recorded with `source_type: "handoff"`;
  `ghostprimer check` passes.
- `test_handoff_json_file_is_accepted_directly`: the file form of
  the input works and is recorded as `input_kind: "file"`.
- `test_secret_inside_handoff_pack_blocks_only_that_item`: an ASIA
  canary planted in an open-loop detail blocks the open-loops item
  (recorded, shape named, canary nowhere in bundle or output) while
  the state and next-steps items still carry forward.
- `test_no_handoff_input_leaves_no_handoff_section`: the default
  path stays clean of the new section and manifest key.
- `test_handoff_items_compete_for_the_memory_share`: on a minimal
  project at `--budget 400`, a long next-step item that does not fit
  the memory share is dropped and recorded in `not_included` while
  the state item is included.

## Demonstration: Handoff closes, Primer reopens

Run Oct 14, 2026 in `/tmp/ghostprimer-seam-demo/` (originals
untouched). A copy of `examples/sample_project` was git-initialised,
committed as a baseline, and given one uncommitted TODO marker in
`src/demoapp/greeter.py`. Then:

```
PYTHONPATH=src python3 -m ghosthandoff pack /tmp/ghostprimer-seam-demo/project \
    -o /tmp/ghostprimer-seam-demo/handoff-pack --json     (from ~/workspace/ghosthandoff)
PYTHONPATH=src python3 -m ghostprimer build /tmp/ghostprimer-seam-demo/project \
    -o /tmp/ghostprimer-seam-demo/primer-out \
    --handoff-pack /tmp/ghostprimer-seam-demo/handoff-pack
PYTHONPATH=src python3 -m ghostprimer check /tmp/ghostprimer-seam-demo/primer-out
```

GhostHandoff's summary: 1 commit in window, 9 files touched,
1 marker, **2 open loops, 2 next steps**.

GhostPrimer's summary: 3 files sliced (114 of 182 tokens), 6 memory
items via fallback (358 tokens), **handoff: 3 items from
`/tmp/ghostprimer-seam-demo/handoff-pack/handoff.json` (249
tokens)**. `ghostprimer check`: `ok: true`, 0 errors.

The manifest's `handoff_input` records the pack directory, its
`handoff.json`, `items_included: 3`, `items_blocked: 0`,
`estimated_tokens: 249`. The PRIMER.md section it produced:

```
## Previous session handoff (source: GhostHandoff pack)

### Previous session state [handoff.json:1]
Branch: master (HEAD 14b2a5d)
Working tree: 0 staged, 1 unstaged, 0 untracked
Changed in window: 1 commit(s), 9 file(s) touched
Latest commit: 14b2a5d baseline
Markers: 1 total (1 in code, 0 in documentation/fixture files)

### Previous session open loops [handoff.json:1]
- [uncommitted-changes] 0 staged and 1 unstaged file(s) are not committed (source: git status)
- [open-markers] 1 open marker(s) in code (TODO 1) (source: marker scan of project files)

### Previous session next steps [handoff.json:1]
1. Work through the TODO markers (1 open); the first listed is at src/demoapp/greeter.py:13. (source: marker scan)
2. Decide on the uncommitted work: 0 staged and 1 unstaged file(s). ... (source: git status)
```

Session N+1 now starts from session N's recorded state instead of
rediscovering it.

## Files

- Changed: `src/ghostprimer/secrets.py` (canonical alignment),
  `src/ghostprimer/bundle.py` (handoff pool, rendering, manifest),
  `src/ghostprimer/cli.py` (`--handoff-pack`, summaries),
  `src/ghostprimer/mcp_server.py` (`handoff_pack` argument),
  `README.md` (new input documented).
- Added: `src/ghostprimer/handoff.py`,
  `tests/test_seam_fixes.py` (7 tests), this report.
- Untouched: every existing test, `pyproject.toml` (version stays
  0.1.0), PLAN.md, and all prior reports.
