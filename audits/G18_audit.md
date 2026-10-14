# G18 Audit — Plugin system for user slicers (v0.23.0)

Goal: let users teach GhostSlice a new language (or override a
built-in) without forking, via a documented plugin contract, with
loading that is always an explicit act, failure discipline that
never kills an export over one file, and cache invalidation keyed
on plugin code. Baseline: v0.22.0, 679 tests passed.

## Build summary

- `src/ghostslice/plugins.py` (new): the whole subsystem.
  Contract, two styles: module attributes (`LANGUAGE`,
  `EXTENSIONS`, `slice_text(path, text, mode)`, optional
  `outline(path, text)`) or `register(api)` with
  `api.register_slicer(language, extensions, slicer, outline=None)`,
  `api.estimate_tokens`, `api.MODES`. One file may register
  several languages. Registrations are validated (language shape,
  extension shape/normalisation, callables) and loaded via
  `spec_from_file_location` under a content-hash module name;
  modules are not inserted into sys.modules, so a repeat load
  re-executes the file.
- Loading points, all opt-in: the profile's `"plugins"` list
  (relative to the project root; the RESOLVED path, symlinks
  followed, must stay inside the resolved root) and `--plugin
  PATH` (repeatable) on export/slice/task/watch, used as given.
  No directory scan, no entry points, no env var. The CLI
  activates the loaded set once per command, before any handler,
  and prints one line per plugin plus the full-privileges trust
  warning. Load failure is PluginError -> exit 2 before anything
  is written. `build_bundle` / `estimate_context_tokens` use the
  active set when one exists, else load the profile's plugins for
  the call; the dashboard activates the profile's set at startup;
  MCP scan/slice/lint handlers load the profile's set per call
  (MCP has no --plugin flag by design).
- Integration: scanner consults the plugin extension map first;
  `slice_source` dispatches to the plugin after full/exclude and
  the core's test-file drop (the core keeps those modes); the
  plugin receives the resolved mode. `outline_source` tries the
  plugin outline, rows validated and clamped to symslice Symbols.
  `is_slicable()` in exporter replaces raw SLICABLE checks in
  exporter/cli/lint/selection/server, so default modes, the fit
  ladder, lint rules, task selection (symbols via the outline),
  and dashboard defaults treat plugin languages as built-ins.
  Manifest gains "plugins" (name/language/extensions/source/
  sha256) and "plugin_errors" blocks when applicable.
- Cache: `ProjectCache` gains a namespace dimension ("ns") in all
  four key builders (slice/symslice/outline/scan); the namespace
  is the plugin set's digest (sha256 over each registration's
  language, resolved path, and file-bytes sha256), "" when no
  plugins are loaded (the pre-plugin key space). CLI cache opens
  pass the active digest.
- Overrides: claiming a built-in language, or an extension a
  built-in owns, is refused unless `--allow-plugin-override`.
  Core pseudo-languages "text" and "config" are refused
  unconditionally (caught during the build's own test pass: the
  first cut let a plugin claim "config", which other modules
  branch on; pinned by test). Duplicate claims on a NEW language:
  last loaded wins, with a note printed at load.
- Example: `examples/plugins/lua_slicer.py`, a parser-lite Lua
  slicer (function...end block matching over a string/comment-
  masked view, long brackets and block comments handled,
  `elseif`/`t.end` edge cases guarded) with a basic outline
  (methods qualified `T.name`), plus `examples/plugins/README.md`.
  Integration tests run scan/export/symbols/symbol-slicing/MCP on
  a Lua fixture using only the example.
- Tests: tests/test_v23_plugins.py, 40 new (679 -> 719). Full
  suite at build: 719 passed, 1 skipped.
- Build-phase self-catch worth recording: `load_for_project`
  initially loaded nothing when called without a profile object,
  which made its own name a lie; it now loads the project's
  profile itself when none is passed (callers pass one only when
  they already hold it).

## Audit #1 — adversarial review of the build

### F1 [MED] A plugin raising SystemExit escapes the failure discipline
`try_slice` / `try_outline` and the loader catch `Exception`.
A plugin calling `sys.exit(3)` in its slicer kills an export
mid-run (probe: exit code 3, no manifest, partial bundle dir);
at load time it exits silently with the plugin's code and no
message. Both violate the goal's discipline (per-file failure
must fall back; load failure must be a clear exit 2).
Fix (Improve #1): catch `BaseException` except
`KeyboardInterrupt` at all three boundaries; load converts to
PluginError, per-file converts to a recorded failure + fallback.

### F2 [MED] Recorded plugin errors are invisible on `slice`, `symbols`, and `explain`
Export and task print the manifest's plugin_errors, and watch
notes them, but the single-file surfaces record errors on the
active set and never print them (probes: `slice` of a file whose
plugin raises returns 0 with "2 -> 2 estimated tokens" and no
warning; `symbols` with an exploding outline counts the file as
"no symbol outline" with no hint a plugin failed). A silent
fallback is exactly what the discipline exists to prevent.
Fix (Improve #1): those handlers call
`plugins.report_errors(active_set(), stderr)` before returning.

### F3 [LOW] Cross-plugin extension re-claim is silent
Two plugins claiming the same extension for DIFFERENT languages:
the later wins the extension map with no note (probe: .zz went
to the second plugin; the first plugin's language became
unreachable by scan). Duplicate LANGUAGE claims do record a
"last loaded wins" note; extension claims should too.
Fix (Improve #1): record a load note when a registration claims
an extension already claimed by another plugin in the same set.

### F4 [LOW] "--plugin <directory>" reports "no such file"
The path exists; the message misleads. Fix (Improve #1):
distinguish missing from not-a-file in the extra-paths check
(the profile branch already reads "no such file under the
project root", acceptable for a contained lookup).

### Checked, no defect
- Containment battery (all refused with clear errors, exit 2):
  profile "../outside.py"; mid-path "tools/../../outside.py";
  absolute profile path; a symlinked plugin FILE inside the root
  pointing outside; a plugin under a symlinked DIRECTORY inside
  the root pointing outside. A symlink resolving INSIDE the root
  loads (same rule as G17's preview containment). Pinned by
  tests including the symlink case.
- Path leakage: error messages use only the label the user
  supplied, plus the resolved path of the user's own refused
  file, printed to the user's own terminal. The manifest's
  "plugins" source is the path as named (relative stays
  relative); manifests already carry the absolute project "root"
  by pre-existing design, so an absolute --plugin path adds no
  new category of disclosure.
- Cache poisoning across plugin versions: the digest covers
  language + resolved path + file-bytes sha256 for every
  registration, and all four cache kinds carry the namespace;
  probe-wise, editing the plugin changed totals on re-export
  (pinned by test). Threaded slicing (--workers 4) recorded a
  failing file's error exactly once (dedupe set on the set).
- Residual cache limitation (documented, not fixed): the digest
  covers the plugin FILE's bytes only. A plugin whose behaviour
  depends on other files (an imported sibling module, a data
  file) can change behaviour without changing its own bytes;
  --no-cache is the escape hatch. The README wording says "file
  bytes" and claims no more.
- Shared-state mutation: a plugin runs in-process and CAN mutate
  GhostSlice module state (e.g. scanner tables) — undetectable
  and unpreventable in-process. Validation snapshots are rebuilt
  per registration, but a mutation lands before the snapshot as
  easily as after. This is the documented trust model (plugins
  are user code with full privileges), not a fixable defect;
  no sandbox is claimed anywhere in the docs.
- Infinite-loop plugin: no stdlib sandbox exists; the trust
  model is stated in README "Plugins" and the plugins.py
  docstring instead of pretending otherwise.
- Non-str returns: bytes/bytearray decode as UTF-8 (documented
  coercion); None/int returns record a failure and fall back to
  full text (pinned by tests). Outline rows are type-checked,
  clamped to the file's line count, and bad rows are skipped
  with a recorded error (pinned).
- No ambient loading: a plugin file sitting unreferenced in a
  project is never loaded (pinned by test); the dashboard and
  MCP read only the profile; `check`/`history` never load
  plugins (nothing they do slices, and history is ledger-only).
- Profile "plugins" of the wrong type fails in profile loading
  (_str_list raises a clear ValueError) before plugin loading
  is attempted; CLI maps it to exit 2 like any bad profile.


## Improve #1 — fixes applied for F1–F4

- F1: `try_slice`, `try_outline`, the loader's exec_module, and
  the register() call now catch `BaseException` except
  `KeyboardInterrupt`: a plugin's `sys.exit()` at load becomes a
  PluginError (probe after fix: "export: plugin
  ./sysexit_load.py: failed to load: SystemExit: 3", exit 2); a
  `sys.exit()` while slicing becomes a recorded per-file failure
  with full-text fallback (probe: export completes, Validation
  OK, warning printed, file ships full text).
- F2: the `slice` (single-file and tree), `symbols`, and
  `explain` handlers now print the active set's recorded errors
  before returning. The shared report wording became kind-aware:
  outline failures say "treated as no outline", slice failures
  "full text used instead" (both printers: plugins.report_errors
  and the CLI's manifest printer).
- F3: a registration claiming an extension another plugin in the
  same set already claimed records a load note ("already
  claimed ... the later plugin wins the extension"), printed by
  the CLI with the other load notes.
- F4: "--plugin <directory>" now reports "not a file"; a missing
  path still reports "no such file".
- Regression tests: +6 in tests/test_v23_plugins.py (46 total):
  SystemExit at load, SystemExit in a slicer, slice/symbols
  error reporting, extension re-claim note + winner, directory
  message. Full suite after Improve #1: 725 passed, 1 skipped
  (679 baseline unweakened).

## Audit #2 — re-review after Improve #1

### F5 [MED] Dashboard /api/export hides plugin failures
The handler mirrors the manifest's fit and redaction blocks
into its response but not the v0.23 blocks: a dashboard export
whose plugin failed on a file answers {"ok": true, ...} with
no hint, while the CLI prints warnings for the same bundle.
The manifest inside the bundle does carry plugin_errors; the
panel user should not have to open it to learn a file shipped
unsliced. Fix (Improve #2): mirror "plugins" and
"plugin_errors" from the manifest into the /api/export
response, exactly like fit/redaction.

### F6 [LOW] MCP slice_file / lint_project drop recorded plugin errors
export_bundle surfaces plugin_errors (it reads the manifest),
but slice_file returns the SliceResult dict bare: a plugin
failure looks like an honest no-op slice (sliced == original),
and lint_project's payload likewise omits the failures its
internal slicing recorded on the per-call set. Fix (Improve
#2): both handlers add "plugin_errors" to their result when
the call's set recorded any.

### F7 [LOW] init's overwrite warning does not mention plugins
`ghostslice init` refuses to overwrite an existing profile
without --force and prints a summary of what the existing
profile holds (ignores, modes, model, budget, entry points,
preset, auto-shrink, lint) — but not plugins. A --force
regeneration drops the "plugins" key, and the one warning the
user gets never names it. Fix (Improve #2): the summary gains
"N plugin(s)" when the existing profile names any.

### Checked, no defect
- Watch: profile plugins load once at startup (announced),
  and --once runs clean on a Lua project; a plugin file edited
  mid-watch is NOT reloaded until restart — consistent with
  the dashboard's startup-snapshot model, and the load lines
  at startup make the set visible. Noted as a limitation in
  the ROADMAP entry.
- Profile path "tools//lua_slicer.py" (double slash) resolves
  and loads; containment is computed on the resolved path, so
  spelling variants cannot smuggle a different verdict.
- A plugin file with a UTF-8 BOM and CRLF line endings loads
  and registers normally (stdlib loader semantics).
- One register() registering the same language twice: last
  wins, one registration survives, the replacement note names
  the file (probe-verified).
- serve loads plugins twice (the CLI's central activation,
  then _State's at startup): the second load replaces the
  first with an equivalent fresh set; module names are
  content-hash keyed, so no stale code survives. Wasteful by
  milliseconds, semantically inert.
- /api/slice and /api/preview on a file whose plugin fails:
  the response carries the honest full text with a 0-savings
  delta (the content is never a partial slice), and the
  failure surfaces at export time on every surface (F5 covers
  the panel). Per-request error fields on the preview
  endpoints are left as a residual: the memoised slice cache
  means the failure may have been recorded by an earlier
  request, and the state's set is a startup snapshot like
  everything else the dashboard serves.
- init never loads plugins: it authors profiles, and the
  plugins key is user-managed; the existing profile is
  protected by the no-force refusal (F7 covers the summary
  gap). Its project analysis therefore treats plugin-language
  files as plain text — acceptable for a generator whose
  output the user reviews, and unchanged from how init treats
  any language it cannot slice.
- Cache key format: all four key builders gained the "ns"
  dimension (empty string without plugins), so entries written
  by v0.22 miss once and are rewritten — a one-time, silent
  cache rotation, not a correctness issue; with no plugins
  loaded the namespace is "" and behaviour is otherwise
  identical to v0.22.


## Improve #2 — fixes applied for F5–F7

- F5: /api/export now mirrors the manifest's "plugins" and
  "plugin_errors" into its response, beside fit and redaction.
- F6: MCP slice_file and lint_project add "plugin_errors" to
  their results when the call's plugin set recorded any
  (export_bundle already surfaced them via the manifest).
- F7: init's existing-profile summary gains "N plugin(s)", so
  the --force warning names the plugin configuration a
  regeneration would drop.
- Regression tests: +3 in tests/test_v23_plugins.py (49 total):
  dashboard export surfacing, MCP slice_file surfacing, init
  summary. Full suite after Improve #2: 728 passed, 1 skipped,
  9 subtests (679 baseline unweakened + 49 new).

## Standing limitations (accepted, documented)

- No sandbox: plugins are user code with full privileges;
  a plugin can loop forever, read the disk, or mutate process
  state. The trust model is stated in README "Plugins", the
  plugins.py docstring, the examples README, and printed by
  the CLI on every load. Nothing stronger is possible in
  stdlib Python, and nothing stronger is claimed.
- The cache digest covers plugin FILES' bytes; behaviour
  imported from sibling modules or data files is outside it
  (--no-cache is the escape hatch).
- Plugin sets are per-process: every CLI run, dashboard
  start, and MCP call reloads from the profile/flags. Watch
  and the dashboard do not hot-reload edited plugins.
- The dashboard preview endpoints show a failing plugin
  file's honest full text; the recorded failure surfaces at
  export time (F5), not per preview request.
