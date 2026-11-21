# Operations

Part of the [GhostSlice README](../README.md). Watching a project, the content cache, doctor, and the MCP server.

## Watch mode (v0.6)

```bash
ghostslice watch ~/my-project                                  # report changes + estimated-token deltas
ghostslice watch ~/my-project --export                         # also rewrite .claude_context on every settled change
ghostslice watch ~/my-project -o /tmp/ctx --interval 2 --fit 20000 --exclude-secrets
ghostslice watch ~/my-project --once                           # snapshot, poll once, report, exit (scripting)
```

Polling watcher (stdlib only, no watchdog dependency). It snapshots
the scanned files every `--interval` seconds (default 1) and reports
a compact delta (files added/removed/changed, estimated tokens
before -> after) once the tree has stayed quiet for the debounce
window (default: the larger of 1s and 2 poll cycles; `--debounce 0`
settles on the first differing poll), so editor/build bursts coalesce
into one event. With `--export` (or `-o`, which implies it) the
bundle is written at startup and after every settled change, exactly
like `ghostslice export`: profile, `--preset`, `--mode`, `--fit`, and
`--exclude-secrets` all apply, each settled export appends at most
one ledger record (one per settled export in normal operation), and
an unfittable or invalid bundle is reported without stopping the
watcher. Watch-written bundles also exclude the bundle directory
itself from their contents when it lives inside the project.

The watcher is loop-proof: the bundle directory (when inside the
project) is excluded from its own change detection and the ledger is
scanner-ignored, so its own writes never trigger events. The bundle
output may not be the project root itself (rejected with exit 2).
With a custom bundle name inside the project, plain scans can still
see a previous bundle's files; prefer the default `.claude_context`
name (scanner-ignored) or a path outside the project. The profile
is reloaded when it changes (v1.0.3): each poll checks the profile
file, and a content change (a bare `touch` does not count) is
validated and applied to subsequent scans and exports without a
restart — including a profile created mid-watch. An invalid edit
keeps the last-good profile and is reported once per distinct bad
content; fixing the file recovers automatically, and deleting it
reverts to the built-in defaults. Plugin changes apply the same
way (v1.0.4): editing the profile's `plugins` list, or a plugin
file's bytes, re-runs the plugin load at the next poll and swaps
the active set when it differs — announced on the watch stream
with the trust warning, since loading executes the plugin. A
failed load keeps the last-good plugin set, is reported once per
distinct bad content, and recovers when fixed; the session
summary counts `plugin_reloads`. `--max-events N` exits after N
settled events. Ctrl-C exits 0 with a session summary (duration,
polls, events, exports).

## Performance: the content cache (v0.20)

Repeat runs are fast because GhostSlice memoizes its own pure
derivations on disk, in `<project>/.ghostslice-cache/`:

```bash
ghostslice export ~/my-project -o /tmp/ctx --timing   # phase breakdown + cache counters
ghostslice scan ~/my-project --timing                 # scan phase vs analysis, cache counters
ghostslice cache stats ~/my-project                   # entries, bytes, age by kind
ghostslice cache clear ~/my-project                   # delete it (derived data; rebuilds on demand)
ghostslice export ~/my-project -o /tmp/ctx --no-cache # bypass the cache for one run
GHOSTSLICE_NO_CACHE=1 ghostslice export ...           # or disable it entirely
```

What is cached: per-file scan derivations (token estimate, line
count, detection evidence), slice results (text + token counts),
symbol outlines, and symbol-slice renders. Since v1.0.2 the
`lint` and `calls` commands route through the same cache (their
scans, the slices lint prices, and the per-file outlines the call
graph builds), each with a `--no-cache` flag like the other
commands; their output is byte-identical off, cold, or warm.
Duplicate detection is not cached — the cache has no kind for
normalized text — so `lint` still re-reads file texts for its
L004 rule. Every entry is keyed
by the sha256 of *all* its inputs — the file's content hash, its
relative path, the slice mode (or sorted symbol keep-set), the
GhostSlice version, and the token-estimator version — so a hit is
the same result the code would have computed, and bundles are
byte-identical with the cache off, cold, or warm (the test suite
diffs whole bundle trees to prove it). A changed file misses
exactly its own entries; a GhostSlice or estimator upgrade moves
the version dimensions and simply misses. Entries are written
atomically (temp file + rename), a corrupt entry counts and reads
as a miss, and a 256 MiB cap evicts oldest-first.

Measured warmups (local, this dev sandbox, medians; see
BENCHMARKS.md for method and caveats): a 2,000-file tree exports
in ~0.65s warm vs ~4.4s cold; this repo exports in ~0.09s warm vs
~2.6s cold. Parallel slicing (`--workers N`) is available and
deterministic, but measured *no faster* for this workload (the
work is regex/AST under the GIL), so it defaults to 1 — the cache
is the win, not thread count.

Trust model, plainly: the cache is trusted derived data, like
ccache's store. Nothing in it is trusted for a security decision
(secret scanning and redaction always run on the final text,
cached or not), but a hand-forged entry would change output —
`cache clear` or GHOSTSLICE_NO_CACHE if that ever matters. The
cache directory is scanner-ignored (never scanned, exported, or
watched); add `.ghostslice-cache/` to your `.gitignore` — it is
regenerable. Estimator changes must bump the estimator version
stamp (`tokens.METHOD_VERSION`) so old entries miss, which is
the same discipline the savings ledger already uses.

## Doctor + shell completions (v1.0)

```bash
ghostslice doctor ~/my-project          # text; --json for machines
ghostslice completions bash >> ~/.bashrc   # or: zsh > ~/.zsh/_ghostslice
```

`doctor` runs ten read-only checks in one screen — Python runtime
vs the supported floor, GhostSlice version (in a source checkout
it also verifies pyproject.toml agrees), the estimator stamp, the
price table (present, parseable, dated), the project profile,
the content cache, the savings ledger (corrupt lines, estimator
mix), the plugins the profile names (loaded to verify, exactly
as any command loads them), git hygiene (.gitignore coverage of
`.claude_context/` and `.ghostslice-cache/`), and workspace
detection. Every warning or failure carries a one-line remedy;
the exit code is 0 unless a check fails. Doctor never writes.

`completions` generates its scripts from the live argument
parser, so the command and flag lists cannot drift from the CLI;
the shipped copies live in `examples/completions/` and are
pinned byte-equal to fresh output by the test suite. They are
generated files shipped as copyable examples, which is why
GhostSlice's own lint flags them as generated content (see
[Known warnings on this repo](../README.md#known-warnings-on-this-repo)).

## MCP server (v0.3)

```bash
ghostslice mcp    # stdio JSON-RPC, newline-delimited
```

Tools: `scan_project`, `slice_file`, `estimate_cost`, `export_bundle`,
`check_secrets` (v0.4), `lint_project` (v0.11), `project_graph`,
`project_history`, and `doctor` (v1.0.5). The surface carries the
CLI's read-only project insights; stateful or writing operations
(watch, init, redact, report files) stay CLI-only, and the
aggregate gates (`ci`, `check-budget`) are compositions of the
tools above plus an exit code. Insight payloads are summaries
with caps, never raw dumps.
Same zero-dependency stdlib pattern as the Ghost Hands MCP server: any
MCP client that can spawn a stdio process can drive GhostSlice.
