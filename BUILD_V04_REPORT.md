# GhostSlice v0.4.0 — Build Report

Date: 2026-10-13. Baseline: v0.3.1 at commit 572bf80, 77 tests passing.
Result: **109 tests passing** (77 baseline + 32 new/updated assertions
across the v0.4 suite; the two MCP tool-count assertions in
tests/test_v03.py were updated from 4 to 5 tools / the exact name set
grew by `check_secrets` — an expansion required by the new tool, not a
weakening). Zero dependencies added; Python stdlib only. No PyPI
publish, no announcements, no GitHub push (local commit only).

## What shipped, per item

1. **Secret guard** (`src/ghostslice/secrets_scan.py`)
   - Patterns: private-key blocks, AWS AKIA/ASIA, GitHub gh[pousr]_,
     OpenAI/Anthropic sk-, Slack xox*, context-gated AWS secret keys,
     passwords in URLs, sensitive-named assignments, generic
     high-entropy assignments.
   - Findings carry path + 1-based line + pattern type + a preview
     redacted to the first 4 characters. Full values are never printed.
   - Surfaces: `ghostslice secrets <path>` (exit 1 on findings, `--json`
     too), secrets section in `scan` (text + JSON), loud stderr warnings
     from `export` and `task`, `export --exclude-secrets` (forces flagged
     files to mode `exclude` in build_bundle), dashboard `/api/secrets`,
     MCP `check_secrets` tool (tool list 4 → 5).
   - False-positive care, all covered by tests: placeholders (example,
     xxx, your-key-here, changeme, dummy, sample, fixture, redacted,
     `${...}`/`{...}` templates, empty) never flag; comment-line
     examples never flag; instructional values (`choose-a-long-secret`,
     `pick-a-long-admin-secret`) never flag; code references and
     expressions (`opts.requireTokens`, `config.token`,
     `sha256(rawToken)`, dict literals like
     `"total_saved_tokens": total_before`) never flag; in code files a
     bare (unquoted) right-hand side is treated as a reference, while
     bare values in env/config/yaml files are still checked; multi-word
     quoted prose strings never flag. These rules were tuned against
     real trees (see Demo) and each tuning has a regression test.

2. **Notebook + Markdown slicers**
   - `.ipynb` (new scanner extension/language `notebook`): parsed with
     stdlib `json`, rendered as text. `signatures`/`interfaces`/`full`
     keep code-cell source only (outputs and execution counts are
     stripped by construction), markdown cells kept as comments;
     `strip-tests` drops test cells (pytest/unittest/test-named);
     `headings` keeps markdown headings + first code line per cell.
     Malformed notebooks return the source for `full` and "" for
     reducing modes, never crash. Notebooks join the slicable defaults
     (export default mode: signatures).
   - `.md`/`.markdown`: new `headings` mode (added to MODES): headings
     plus the first paragraph under each heading. Docs still default
     to `full`; opt in via per-glob/profile or `--mode`. `headings` on
     non-doc files is a no-op full fallback.

3. **Duplicate detection** (`src/ghostslice/duplicates.py`)
   - Exact: sha256 of normalized content (trailing whitespace stripped,
     trailing blanks dropped; <20 normalized chars ignored).
   - Near: line-shingle Jaccard >= 0.85, documented threshold, only for
     files with >= 8 distinct lines and >= 200 normalized characters.
   - Surfaced in `scan` (text + JSON), `graph` prune recommendations
     (duplicate copy flagged with token saving; also in `--json`),
     dashboard `/api/graph` (`duplicates` key; recommendations already
     include duplicate candidates), and the HTML report.
   - Tests: exact detected, near detected, distinct file not flagged,
     duplicate becomes a prune candidate even when reachable/imported.

4. **Parser-lite robustness hardening** (`slicer.py` `_brace_end`)
   - Brace matching is now string/comment aware with state persisted
     across lines: `'...'`, `"..."`, template literals including
     `${...}` interpolation and multi-line templates, `//` comments,
     `/* ... */` block comments. Shared by TS/JS and (via `_block_end`
     with a language argument) Go/Rust/Java/C#; for those, single
     quotes use a char-literal heuristic so Rust lifetimes (`'a`) do
     not open phantom strings.
   - Adversarial golden tests: template literal containing `}`, string
     containing `{`, commented-out braces, block comments spanning
     lines, Go strings/comments, Rust lifetimes + `"}"` string.
   - Remaining limit, documented in README + docstring: braces inside
     regex literals (e.g. `/}/`) and nested backticks inside `${...}`
     can still confuse the counter.

5. **Standalone HTML report** (`src/ghostslice/report.py`)
   - `ghostslice report <project> -o report.html [--model ID]`: one
     self-contained file, inline CSS, violet accent #6716f3, no
     external assets, no JS needed. Contains scan totals, top-50 files
     by tokens with heat bars, sliced estimate + pre-flight cost at
     the selected model (local dated prices, labelled), prune
     recommendations, duplicate findings, redacted secret findings,
     savings history. All project strings HTML-escaped (tested with a
     `weird<name>.py` fixture: appears as `weird&lt;name&gt;.py`).

6. **Explain command**
   - `ghostslice explain <project> <relpath> [--mode MODE]`: included
     or not, and why (profile ignore, .gitignore, scanner defaults,
     missing file); resolved mode and why (explicit / profile per-glob /
     default with the specific default reason: test, lockfile, code,
     non-code); original vs sliced estimated tokens; imports and
     importers from the graph; duplicate flags; secret flags (redacted).

## Demo: GhostBus (~/workspace/ghostbus, a working checkout, not a git repo)

- Scan/dashboard numbers **unchanged** from the v0.3 demo: 42 files,
  **164,988 estimated tokens**. Export via the API
  (`build_bundle(..., record_history=False)`, bundle in /tmp so the
  GhostBus tree was not modified): 164,988 -> **53,339** sliced
  estimated tokens (saved 111,649), bundle validation OK. No change
  because GhostBus has no notebooks/markdown-default changes and the
  brace hardening did not alter its sliced output totals.
- Dashboard smoke against GhostBus: `serve` on port 8799 — `/` 200
  (dashboard HTML), `/api/scan` 200 with totals above, `/api/secrets`
  200, `/api/graph` includes the new `duplicates` key (no duplicates
  found in GhostBus).
- Secret guard on GhostBus: **2 findings**, both quoted literal dummy
  keys hard-coded in test/bench scripts
  (`deploy/netlify/test-lib.mjs:107`, `scripts/load-bench.mjs:36`,
  both redacted in output). During tuning the guard initially also
  flagged GhostBus documentation placeholders
  (`GHOSTBUS_KEY=choose-a-long-secret`, `pick-a-long-secret`) and code
  expressions (`a.tokenHash = sha256(rawToken)`,
  `this.requireTokens = !!opts.requireTokens`); those false-positive
  classes are now excluded by rule, with regression tests.
- Secret guard on GhostSlice's own repo: **clean** (0 findings,
  `ghostslice secrets .` exits 0). Test fixtures assemble fake token
  shapes from string fragments at runtime, so no credential-shaped
  literals live in the source.

## Tests

- Before: 77 passed. After: **109 passed**
  (`PYTHONPATH=src python3 -m pytest tests -q`).
- New file `tests/test_v04.py`: 32 tests covering secrets hits +
  non-hits + redaction/line numbers, secrets CLI exit codes,
  export --exclude-secrets (API + CLI), MCP check_secrets, dashboard
  /api/secrets + /api/graph duplicates, notebook golden + malformed,
  markdown headings golden, duplicates exact/near/distinct + prune
  candidate, adversarial TS/Go/Rust parser-lite cases, report totals /
  escaping / redaction + CLI, explain included / gitignored / test-file.
- `tests/test_v03.py`: only the two MCP tool-list assertions changed
  (exact set now includes `check_secrets`; stdio count 4 -> 5).

## Known limitations

- Secret guard is heuristic: it favours not flagging placeholders and
  code expressions over catching every shape. Bare unquoted literal
  secrets in code files (invalid style in most languages) and
  passphrase-style multi-word quoted secrets are not flagged.
  Hard-coded literal dummy keys in test/bench scripts DO flag (they
  are literal keys; a human confirms they are dummies).
- Parser-lite: regex-literal braces and nested backticks inside
  `${...}` can still miscount (documented). Python remains the only
  real-parser language; notebook `interfaces` reuses the signatures
  rendering (notebooks have no separate interface surface).
- Near-duplicate detection is pairwise over files above the size
  floor; fine for project-scale trees, not tuned for monorepos with
  tens of thousands of files.
- Token counts remain estimates and prices remain the local dated
  snapshot (2026-10-12), as before.

## Files changed

- New: `src/ghostslice/secrets_scan.py`, `src/ghostslice/duplicates.py`,
  `src/ghostslice/report.py`, `tests/test_v04.py`,
  `BUILD_V04_REPORT.md` (this file).
- Modified: `src/ghostslice/slicer.py` (brace hardening, notebook +
  markdown slicers, `headings` mode), `src/ghostslice/scanner.py`
  (.ipynb/.markdown), `src/ghostslice/cli.py` (secrets/report/explain
  commands, scan/graph output, export --exclude-secrets, task/export
  warnings), `src/ghostslice/exporter.py` (exclude_secrets, notebook
  slicable), `src/ghostslice/graph.py` (duplicate prune candidates),
  `src/ghostslice/server.py` (/api/secrets, /api/graph duplicates),
  `src/ghostslice/mcp_server.py` (check_secrets tool),
  `src/ghostslice/__init__.py` + `pyproject.toml` (version 0.4.0),
  `README.md`, `CHANGELOG.md`, `tests/test_v03.py` (tool-list counts).

Not done (separate Ryan gates, untouched): no GitHub push, no PyPI
publish, no announcements.
