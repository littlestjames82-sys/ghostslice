# GhostIndex
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostindex/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostindex/actions/workflows/ci.yml/actions)

**Find which project, and which file, holds the thing you half remember, before you slice anything.**

By Ghost Developer Studio. Working name, v0.1 per `PLAN.md`. Zero-dependency Python stdlib, local only, offline, MIT pattern.

GhostSlice cuts one project's context down once you have chosen the project. GhostIndex answers the question that comes first: across every checkout on your machine, where does this term actually live? You name the project roots. GhostIndex walks them once, stores the text in a local sqlite FTS5 index, and answers later searches from that index with ranked, bounded excerpts: root, relative path, line ranges, the matching lines with a few lines of context, and token estimates for the excerpt and for the whole file, so the cost of pulling a file in full is visible before anyone pays it.

Story in the stack: Index (find) -> Slice (cut) -> Verify (check). Index never slices a bundle and never exports context packs. It points at files; Slice does the cutting.

## Quick start

Needs Python 3.10 or newer. There is nothing to install beyond that: zero dependencies, Python stdlib only.

From a source checkout:

```bash
PYTHONPATH=src python3 -m ghostindex index ~/code/project-a ~/code/project-b
PYTHONPATH=src python3 -m ghostindex search "quixotic login"
```

Or installed (`pip install .` from the checkout), the same commands as `ghostindex ...`.

The index database lives at `~/.local/state/ghostindex/index.db` by default. Choose the file with `--db <path>` on any command (it goes after the command name, for example `ghostindex search "login" --db /tmp/demo.db`), or set `GHOSTINDEX_DB` in the environment. Project trees are never written to by indexing or searching.

New here? `examples/` holds two tiny projects and a captured session you can reproduce in under a minute; see Examples below.

## Typical workflow

1. **Index once.** Name every checkout you want searchable: `ghostindex index ~/code/project-a ~/code/project-b`. Only the roots you name are ever walked.
2. **Search as questions come up.** `ghostindex search "quixotic login"` answers from the index, so repeat searches do not rescan the projects.
3. **Refresh when projects change.** `ghostindex update` re-indexes every known root by file hash and reports exactly what was added, changed, removed, and unchanged. There is no watcher; the index only moves when you run `index` or `update`.
4. **Housekeep occasionally.** `ghostindex list` shows what is indexed, `ghostindex stats` shows database size and any space a `ghostindex vacuum` would reclaim, and `ghostindex remove <root>` drops a checkout you no longer want searchable.
5. **Check health when something looks wrong.** `ghostindex doctor` reports FTS5 availability, the database, and any indexed root that has moved or been deleted.

## Commands

| Command | What it does |
|---|---|
| `ghostindex index <root> [<root> ...]` | Index one or more named project roots (added / changed / removed / unchanged counts printed per root) |
| `ghostindex update [<root> ...]` | Incremental re-index by size, mtime, then sha256; with no roots it updates every indexed root |
| `ghostindex search "<terms>"` | Ranked search returning sliced excerpts, never whole files |
| `ghostindex list` | Every indexed root with file counts, estimated tokens, last update time |
| `ghostindex stats` | Database path and size, totals, per-root and per-language breakdown |
| `ghostindex remove <root>` | Drop one root from the index and compact the database, so its space is actually reclaimed; nothing in the project itself is deleted |
| `ghostindex vacuum` | Compact the index database, reclaiming space left behind by removed or changed files |
| `ghostindex doctor` | Report sqlite version, FTS5 availability, database path and size, and any indexed root missing from disk |

Search options: `--root <path>` restricts to one indexed root, `--limit N` caps hits, `--context N` sets context lines around each match (default 3), `--max-tokens N` caps the total excerpt budget across hits, `--any` matches files holding any term instead of all terms (the default), and `--json` prints machine-readable hits for agents. Run `ghostindex search --help` (or `--help` on any command) for the full flag list with defaults.

`index` and `update` do the same work: both walk the named roots and diff by hash, so re-running `index` on a known root is safe and incremental. `update` exists for the common case where you want every known root refreshed without naming them again.

Query syntax inside the search string: plain terms must all be present (any of them with `--any`), a trailing `*` makes a term a prefix (`draft*` matches draft and drafting), a quoted `"two words"` is a phrase and matches only files where the words occur in that order, adjacent as tokens (a file holding both words apart does not match), and `-term`, `-term*`, or `-"two words"` excludes every file containing that term or phrase, however well it matches the rest. For example, `ghostindex search 'sunflower -"sunflower festival"'` finds files about sunflowers that never use the exact festival phrase. Exclusions apply in the index query itself, so `total_matches` and the cap accounting already reflect them. A query made only of exclusions has nothing to rank and exits 2. A query that itself starts with `-` needs the standard `--` separator before it, with any `--db` placed before the `--`.

Caps are never silent. Every search states how many files matched in total, and when a limit cuts the result (the hit limit, the total token budget, or the per-hit cap shortening an excerpt) the output says so and names the limit that bound, in text and in `--json` (`total_matches`, `shown`, `capped`, `capped_by`, `limits`, and `excerpt_truncated` on any shortened hit). `stats` and `doctor` print the same default caps as `search_defaults`, so the numbers agree across commands.

Search exit codes: **0** means matches found, **1** means no matches, **2** means the search could not run (no index at that path, a bad root filter, or FTS5 unavailable). A broken index is never reported as a silent empty success.

Every command accepts `--db <path>` and `--json` where noted in `--help`.

## What gets indexed, and what does not

Indexed: text-shaped files under the roots you named, under a size cap (default 2 MiB, set with `--max-bytes`).

Never indexed:

- Files and folders matched by a root's `.gitignore`, or by the `ignore` list in a root's `.ghostslice.json` profile.
- The default ignore dirs GhostSlice also skips (`.git`, `node_modules`, `dist`, `build`, `__pycache__`, virtualenvs, caches, and friends).
- Binary files (by extension, the same set Slice's scanner uses: images, archives, executables, fonts, media, `.pyc`, database files, and more).
- Anything outside the roots you named. There is no default home-directory crawl, ever.

Indexing, updating, and searching write nothing into a project root. The only file created is the index database itself.

## How search results are shaped

Each hit names the project root and the relative path, the line ranges covered, and one or more excerpt windows: plus/minus context lines around the match lines, overlapping windows merged, match lines marked with `>` in text output. Each hit carries an excerpt token estimate and a whole-file token estimate from GhostSlice's calibrated estimator when a GhostSlice install or sibling checkout is reachable, with a documented fallback estimator when it is not. Token figures are **estimates** everywhere they print, labelled with the method in force. They are budgeting aids, not tokenizer truth.

The header of every search result counts the matching files before any capping (`10 of 30 matching file(s)`), and a `note:` line names any cap that bound. A hit whose excerpt was shortened by the per-hit token cap is marked as shortened, in text and as `excerpt_truncated` in `--json`.

Reading one hit, top to bottom: the numbered line gives the relative path, language, and whether the file matched in its body or only by name; the next line gives the root it lives under; the token line prices the excerpt against pulling the whole file; then each window prints its line range (`L12-L18`) followed by the lines themselves, with `>` on the lines that matched.

## Search tips

- **All terms by default.** `ghostindex search "quixotic login"` only returns files holding both terms. Add `--any` when either term alone is enough.
- **Prefix terms end in `*`.** `ghostindex search "auth*"` matches `auth`, `authenticate`, `authorise`, and so on.
- **A term can match a file name.** If the term is in a file's path but not its body, the hit is labelled a name match and shows the head of the file instead of a match window.
- **Narrow before you widen.** `--root <path>` limits a search to one indexed root; `--limit N` and `--max-tokens N` bound how much comes back. When a cap binds, the output says so; raise the limit named in the `note:` line to see more.
- **Quote the query.** The terms are one argument, so `ghostindex search quixotic login` is not the same command: the shell would treat `login` as an extra argument and the CLI would error.
- **Use `--json` for scripts and agents.** It carries the same hits plus the cap accounting (`total_matches`, `shown`, `capped`, `capped_by`, `limits`), so a caller can tell a complete answer from a capped one without parsing text.

## Honest limits

- **Keyword full-text search only.** v0.1 is sqlite FTS5 with bm25 ranking. There is no semantic search, no embeddings, no LLM reranking, and no query understanding. A file that says it differently will not be found.
- bm25 ranks text relevance only. It knows nothing about code structure, so a heavily commented mention can outrank a terse definition. Excerpts show the match lines so a human or an agent can judge.
- The `.gitignore` matcher is a pragmatic subset (patterns, negations, directory rules, globs). Edge cases can differ from git's own answer; the common cases are pinned by tests.
- Excerpts are windowed by lines, and a single very long line (a minified bundle line, a generated one-liner) is cut mid-line around the match, with the cut ends marked, so the per-hit token cap holds even then. (This was a defect in the first v0.1 build, fixed Oct 14, 2026; see FIX_REPORT.md.)
- FTS5 stores a full copy of the indexed text inside the database file. Indexing large project sets makes a real file on disk; `doctor` reports its size. Deleted content's space is reclaimed explicitly: `remove` compacts the database as part of dropping a root, `stats` shows how many bytes are reclaimable at any time, and `ghostindex vacuum` reclaims space freed by updates without dropping a root.
- No watching: the index changes when you run `index` or `update`. Change signals belong to GhostWatch.
- No network code exists in the tool. Nothing leaves the machine.

## Troubleshooting

- **`error: no index database at ...` (exit 2).** Nothing has been indexed at that database path yet. Run `ghostindex index <root>` first, and check `--db` / `GHOSTINDEX_DB`: a search against a different database file than the one you indexed is the usual cause.
- **`error: root not in the index: ...` (exit 2).** `--root` only accepts a root that is already indexed. `ghostindex list` shows the exact root paths the index knows.
- **A term you know exists returns no matches (exit 1).** Work through the usual causes in order: the file may have changed since the last `index` / `update`; the file may be ignored (a `.gitignore` rule, the profile `ignore` list, or a default ignore dir), binary, or over the `--max-bytes` cap, in which case it was never indexed by design; or the file may phrase it differently, because this is keyword search (see Honest limits). Searching for an ignored file's planted term is demonstrated in the sample session.
- **`FTS5 MISSING` in `doctor`, or `sqlite FTS5 is not available` (exit 2).** This Python's sqlite build lacks FTS5, and GhostIndex cannot run without it. Use a Python build with FTS5 enabled; `ghostindex doctor` is the quickest check.
- **The database keeps growing.** Updates free space inside the file without shrinking it. `ghostindex stats` shows how many bytes are reclaimable; `ghostindex vacuum` reclaims them, and `ghostindex remove <root>` compacts as part of dropping a root.
- **A root is flagged as no longer on disk.** The checkout moved or was deleted. Either `ghostindex remove <old root>` and index the new location, or just index the new location and remove the stale entry when convenient. The stale entry's files stay searchable until you do, pointing at a path that is gone.

## Examples

`examples/` holds two tiny projects that share the phrase "sunflower festival", plus a captured sample session (`examples/sample_search_session.md`) showing an index run, a cross-project search, a search for an ignored file's term returning no matches, and stats. `examples/README.md` gives the four commands to reproduce the session yourself against a scratch database.

## Layout of this repo

| Path | What it is |
|---|---|
| `PLAN.md` | The v0.1 design: scope, contract, verification bar, risks |
| `src/ghostindex/` | The core: scanner, store (sqlite FTS5), indexer, search, CLI |
| `tests/` | Black-box CLI tests, fixture projects, hard-rule proofs |
| `examples/` | Two tiny fixture projects and a captured sample session |

---
<!-- ghost-studio-footer -->
## More from Ghost Developer Studio

Ghost Developer Studio builds developer tools, AI-agent safety software, and practical apps, and sells by showing working software, not slide decks.

- [Roadmap board](https://github.com/littlestjames82-sys/ghost-roadmaps): where every studio product stands
- [Agent Seatbelt](https://github.com/littlestjames82-sys/agent-seatbelt): deterministic guardrails for AI coding agents
- [Ghost Hands](https://github.com/littlestjames82-sys/ghost-hands): governed, recorded, replayable agent hands
- [GhostSlice](https://github.com/littlestjames82-sys/ghostslice): agent context and prompt optimizer
- [GhostIDE](https://github.com/littlestjames82-sys/ghostide-android): fully offline AI code editor for Android
- [All studio projects](https://github.com/littlestjames82-sys?tab=repositories)
