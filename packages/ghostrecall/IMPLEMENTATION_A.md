# GhostRecall v0.1 - Agent A (core builder) implementation report

Scope owned: `src/**`, `pyproject.toml`, `IMPLEMENTATION_A.md` only.
Tests and README were NOT edited (Agent B territory).

## What was built (src/ghostrecall/)

- `tokens.py` - BPE-like token estimator aligned in method with GhostSlice's
  prose calibration; every count labelled an estimate, not an exact tokenizer count.
- `secrets.py` - secrets carry-over guard (GhostSlice v0.4 style): provider token
  shapes + generic secret assignments + private keys; findings carry path + line +
  type ONLY, never the value. Items with findings are blocked from export.
- `model.py` - provenance model. Every item carries Provenance (project-relative
  path + 1-based line, or a git commit). Items without valid provenance are dropped
  by the walkers and never exported (anti-hallucination rule from PLAN.md).
- `profile.py` - the `recall` section of the project's `.ghostslice.json`.
  Allowed keys: recent_n, default_mode, memory_budget_fraction (default 0.2,
  labelled a default), pinned_rules, include_git, git_limit, max_items.
  Unknown recall keys raise ValueError naming the key.
- `sources.py` - project-local walkers:
  - Markdown/text notes, docs/, ADRs, CHANGELOG-style files (section-split items).
  - Session notes: `audits/`, `*REPORT.md`, `ROADMAP*`, `BUILD*` classified `session_note`.
  - `DECISIONS.md` parser: one decision per `## ` heading block, fields
    Date / Decision / Reason / Supersedes / Tags / Status / Rule. Supersedes links
    resolve after collection and mark the older decision superseded.
  - Git history via local `git log` only (no hosting API, no network).
  - HARD BOUNDARY: root resolving to `~/MEMORY.md`, `~/memory/**`, `~/.MEMORY.md`,
    or the home directory itself is refused; paths resolving to private memory are
    excluded; symlinks escaping the project root are not followed; ignore dirs
    (.git, node_modules, dist, caches, export folders) skipped.
- `modes.py` - extractive modes only: full, decision-only, headings (heading +
  first paragraph line), recent (selection-level), exclude. No LLM, no summarising.
- `recall.py` - TF-IDF ranking over decisions + note sections + commits, token
  costs shown; rule pinning (decision tags rule/pinned/standing or profile
  pinned_rules) always includes pinned items and marks them pinned, not ranked;
  superseded decisions are never served as current (excluded with reason, or
  served flagged if explicitly pinned); supersedes relationships surface as
  conflicts instead of being silently resolved; `explain` reports selected and
  NOT-selected items with reasons.
- `bundle.py` - combined bundle: `manifest.json`, merged `PROMPT.md`,
  `RECALL.md`, `files/` (sliced memory items), `slice_manifest.json` copy when a
  GhostSlice bundle is passed with `--slice-bundle` (its files become code items
  in the merged manifest and its PROMPT.md leads the merged prompt). `--fit` uses
  memory_budget_fraction of the total when a slice bundle is present, downgrades
  non-pinned items to decision-only, then drops lowest-ranked non-pinned items.
  Excluded items (superseded / blocked / over-budget) are recorded in the manifest
  as excluded with reasons. Blocked (secret) items are never written.
  A ledger line is appended to `<project>/.ghostrecall-history.jsonl`.
  `check_bundle()` verifies each exported file's sha256 and sliced token total
  against the manifest and that provenance is present.
- `dashboard.py` + `dashboard_panel.html` - dashboard panel fragment (heat list,
  pinned rules first, include/exclude, combined total), HTML-escaped only.
  (Embedding it into GhostSlice's own dashboard is cross-repo and out of A's files.)
- `mcp_server.py` - stdio JSON-RPC MCP server, tools `recall_search`,
  `recall_bundle`, `recall_explain`; capped payloads (20 results, 2000-char previews).
- `cli.py` - `ghostrecall scan|recall|explain|bundle|check|panel|mcp`, `--version`.

`pyproject.toml` - ghostrecall 0.1.0, zero dependencies, console script.

## Smoke test (fixture project in /tmp/grfix, git-initialised)

Fixture: DECISIONS.md with 3 decisions (an old file-storage decision superseded by
a database decision, plus a Rule:true standing rule), docs/guide.md, a note with a
planted `sk-proj-...` key, one git commit.

- `scan` - 7 items (3 decisions, 2 doc sections, 1 secret note, 1 commit),
  old decision already marked `superseded`. Exit 0.
- `recall --task "database storage for widgets" --explain` - pinned rule included
  first (score 0.0, marked pinned); commit and database decision rank top;
  superseded decision listed not-selected with reason `superseded`; secret note
  not-selected with reason `secret-finding (blocked)`; supersedes conflict flagged.
- `bundle --fit 10000` - 5 memory items, 142 estimated sliced tokens; `check` OK.
  `grep` for the planted key over PROMPT.md and manifest.json: 0 hits.
- Combined bundle with a fake Slice bundle via `--slice-bundle` - merged manifest
  carried 1 code item + 5 memory items, memory budget 1000 (0.2 x 5000 fit),
  `check` OK.
- MCP stdio - initialize, tools/list, recall_search and recall_explain calls all
  returned JSON-RPC results.
- Private-memory boundary - `scan ~/memory` refused with
  "refusing private assistant memory as a project source".
- Profile discipline - a `recall` section with a bogus key failed loudly naming it.
- Installed form - `pip install .` in a fresh venv succeeded and the installed
  `ghostrecall scan` console script produced the same fixture totals.
- `panel` renders the panel HTML with pinned item first.

## Known limits (v0.1, per plan)

- TF-IDF only, no embeddings (plan defers semantics to a v0.2 candidate).
- DECISIONS.md format is heading-block based; freeform files work as notes.
- Dashboard panel is a fragment/helper, not a running server, per plan
  ("one extra panel in Slice's dashboard, not a second server").
- Token counts are estimates (method string is recorded in every manifest).
