# Polish Audit — v1.0.4: cyclic-symlink sweep, Go/Rust symbol depth, watch plugin reload

Round: post-marathon polish round 4 (Ryan: "Continue").
Baseline v1.0.3, local HEAD 817a1d1, 864 tests. Three items:
hardening for the surfaces the v0.21 fuzz round never swept,
demonstrate-then-fix depth for the Go/Rust lite parsers, and
closing the watch profile-reload limitation round 3 documented.
Zero-dependency stdlib only; no PyPI publish, no announcements —
those gates were never opened.

## Before / after

| Probe | Before (v1.0.3) | After (v1.0.4 work) |
|---|---|---|
| Full test suite | 864 passed | (final count in the closing section) |
| `detect_workspaces` on the cyclic fixture | phantom DECLARED packages `pkgs/ext` (resolves outside the root) and `pkgs/linkd` (resolves to an ancestor), no warnings | both skipped, each with a "reached through a symbolic link" warning; real member `pkgs/one` unaffected |
| Dashboard / CI / watch / MCP on cyclic trees | unpinned (G16 accepted the gap) | pinned: all answer/terminate; dashboard never serves outside content (403/400) |
| Go outline of the generics fixture | `Map`, `Min` MISSING; `Pair.Swap` qualified as `V].Swap`; generic interface methods not enumerated | all present and correctly parented (below) |
| Go `slice` signatures of the same | generic functions AND generic type declarations dropped whole | all present |
| Rust outline of the generics fixture | impl for `Wrapper` named `>` (method `>.total`); where-clause trait impl not a region (`next` a parentless free function) | `Wrapper.total`, `Pair.next`, correct impl symbols |
| `watch` plugin changes | not re-applied; restart required (round 3 documented limit) | list changes and byte edits apply at poll tops; failures keep last-good, one report per distinct bad content |
| GhostBus demo export | 129,555 -> 45,770 | unchanged (test_v13 pin) |
| `secrets .` | exit 0 | exit 0 (final verification) |

## Item A — cyclic-symlink sweep

Fixture (built in /tmp for the probes, rebuilt by the shipped
tests): a project with `sub/loop -> ..` (cycle), `sub/self -> .`,
a dangling `a_link <-> b_link` loop, `outside_link` -> a
directory outside the root, `pkgs/linkd -> ../pkgs` (declared
member aliasing an ancestor of the real member `pkgs/one`),
`pkgs/ext` -> outside (declared member escaping the root), and
`escape.py` -> an outside file (file symlinks are followed by
design since v0.21).

Demonstrated before-state, surface by surface:

- **Scanner**: terminates; yields exactly the 6 real files, no
  path through any cycle. Already safe (os.walk
  followlinks=False + the v0.21 regular-file gate) — the pin is
  the deliverable.
- **Workspace detection — THE GAP.** `detect_workspaces`
  returned declared packages `pkgs/ext` and `pkgs/linkd` with
  NO warnings: `_expand_pattern` judged candidates with
  `Path.is_dir()`, which follows symlinks, defeating the
  module's own containment rule ("detection never reaches
  outside the root" held only for `..` patterns). Neither
  phantom can ever own a scanned file, and `pkgs/ext` claims a
  package whose content lives outside the project. The
  fallback had the same shape: a symlinked child carrying (or
  leading to) a manifest was reported as a detected package,
  including a `selflink/real` phantom duplicating a real package
  under a second name.
- **Dashboard** (probed over HTTP): /api/scan and /api/graph
  answer 200 with the true file set; /api/preview and
  /api/slice for `escape.py` return 403 ("path resolves outside
  the project") and a `../` traversal returns 400; the outside
  marker string appears in NO response. Already safe — pins.
- **CI** `run_ci` on the fixture terminates with all five check
  verdicts. **MCP** `scan_project` answers with a result.
  **Watch**: introducing `sub/loop` and an escaping dir link
  mid-run (scripted sleep) does not hang the poll loop, does
  not leak outside paths, and the real change in the same cycle
  is still reported. All already safe — pins.

Fix (the one real change): detection now only accepts a
directory the scanner's walk would actually descend into —
`_is_real_dir(root, rel)`: the candidate exists, is a directory,
is not itself a symlink, and its resolved path relative to the
resolved root is itself. Applied in `_expand_pattern` (glob
children and literal segments, so negations behave the same)
and in the fallback's directory enumeration (no symlinked
children). A declared literal member that exists only through
a symlink is skipped with a warning naming it ("reached through
a symbolic link; skipped") instead of being misreported as
`missing`. This is one rule with no special cases: cycles,
escapes, and ancestor aliases all resolve somewhere else, and
"somewhere else" is never a package dir. After-state on the
fixture: packages `["", "pkgs/one"]`, two warnings, `missing`
empty; the CLI's scan JSON `packages` agrees.

## Item B — Go + Rust depth (demonstrate, then fix)

Fixtures: a realistic generic Go stack (generic struct + pointer
and value generic receivers, generic functions `Map`/`Min`, a
generic interface) and a realistic Rust stack (three inherent/
trait impl blocks for one type, a where-clause trait impl, an
impl whose header carries an associated-type binding).

Demonstrated before-state (outline / selection / signatures):

- **Go G1 — generic functions invisible.** `Map[T any, U any]`
  and `Min[T Ordered]` matched no outline entry at all (the
  func pattern required `(` right after the name), so
  `slice --symbols Map` reported the symbol unknown and
  signatures mode dropped both functions whole. The same
  pattern is duplicated in slicer.py (`_GO_FUNC_RE`, signatures
  mode) and selection.py (task-selection name extraction) — all
  three missed them.
- **Go G2 — multi-parameter generic receivers mis-parented.**
  `func (p Pair[K, V]) Swap()` outlined as qualified `V].Swap`,
  parent `V]`: the receiver type was `split()[-1]` of the
  receiver text, and gofmt's space after the comma in
  `Pair[K, V]` made the last "token" `V]`. Selecting the real
  name `Pair.Swap` kept nothing. Single-parameter receivers
  (`*Stack[T]`) worked — which is why Push/Pop looked fine.
- **Go G3 — generic type declarations invisible to signatures
  mode, generic interface methods unenumerated.** `_GO_TYPE_RE`
  required `type Name struct|interface` adjacency, so
  `type Stack[T any] struct` was dropped from signatures output
  whole, and `_go_outline`'s interface check (same regex) never
  fired for `type Ordered[T any] interface`, so its methods
  were never enumerated as symbols.
- **Rust R1 — nested generics name an impl `>`.**
  `impl<I: Iterator<Item = u8>> Wrapper<I>`: `_rust_impl_type`
  stripped generics with a flat `<[^>]*>`, which stops at the
  FIRST `>` (the binding's close), leaving the second `>` as
  the "type name". Outline: an impl symbol named `>`, method
  qualified `>.total`; selecting `Wrapper.total` kept nothing.
- **Rust R2 — where-clause impls are not regions.**
  `impl<T> Iterator for Pair<T> where T: Clone, {` (brace lines
  later): the impl branch required `{` on the impl line, so the
  block was never entered; `next` outlined as a parentless
  top-level FUNCTION, no impl symbol existed, and selecting
  `Pair.next` kept nothing (bare `next` kept it by accident,
  ambiguously).
- **Hypotheses that did NOT reproduce** (dropped, per the
  brief): multiple impl blocks for one type are NOT merged —
  three `Stack` impl symbols with distinct, correct spans, and
  every method attributed to `Stack`; a same-line trait impl
  (`impl<T> fmt::Display for Stack<T>`) attributes `fmt` to the
  implementing type correctly; generic impls with simple bounds
  (`impl<T: Clone> Stack<T>`) were already fine.

Fixes (lite-parser honesty preserved — still line/brace
matching, no AST claims):

- The func pattern in all three copies (symslice `_go_outline`,
  slicer `_GO_FUNC_RE`, selection `_GO_FUNC_RE`) and
  `_GO_TYPE_RE` now allow an optional bracketed type-parameter
  list (one nesting level, for constraints like `~[]int`)
  between the name and the parameter list / type kind.
- `_go_receiver_type`: splits the receiver on whitespace that
  sits OUTSIDE the brackets, takes everything after the
  receiver name (or the bare type for unnamed receivers), then
  strips `*` and type arguments — `Pair[K, V]` -> `Pair`.
- `_rust_impl_type` strips generic spans with a nesting-aware
  scanner (`_strip_generic_spans`); `->` inside a span is an
  arrow (Fn-trait bounds), never a span close.
- `_rust_region`'s impl branch finds the block's opening brace
  with the slicer's own `_find_block_brace` (paren-depth 0, a
  `;` first means no block, 8-line window) instead of requiring
  it on the impl line; the impl symbol's head now spans the
  full header (impl line through brace line) and the region
  starts after the brace. Same-line headers behave exactly as
  before.

After-state: the full before/after outline and selection tables
were re-run on both fixtures; every demonstrated case now
outlines, parents, selects, and signature-renders correctly,
and the previously-working cases (Push/Pop, Display::fmt,
separate impl blocks) are unchanged. Audit #1 probes: unnamed
generic receivers (`func (Stack[T]) Len()`), an impl whose
brace sits on the line after the where clause's last bound,
and a plain impl with the brace on the next line (no where) —
the last also works now, as a side effect of finding the brace
instead of assuming its line.

Still limited, recorded not fixed: multi-line `where` clauses
on TYPE declarations (`trait Greeter where ... {`) — the trait
symbol appears but its methods are not enumerated (same shape
as R2, different parser branch; this round's scope was impl
blocks, per the brief). A type-parameter constraint containing
a literal `[]` beyond one nesting level, and braces inside
where-clause const-generic expressions, remain lite-parser
edges.

## Item C — watch plugin reload

Round 3 left the documented limit: profile reload did not
re-apply the `plugins` list. Now, when the session manages
plugins (`run_watch(..., manage_plugins=True)` — the CLI passes
it, together with the `--plugin` / `--allow-plugin-override`
values the startup load used):

- Trigger: the poll-top reload check stats every plugin file
  the LIVE profile names (profile-relative) plus the session's
  `--plugin` files. A changed plugins list (via a profile
  reload in the same or an earlier poll) or a moved stat on any
  plugin file re-runs `plugins.load_for_project` — the startup
  load's exact validation and containment. Most polls end at
  the unchanged-signature comparison; no load executes.
- Swap: the new set replaces the active one via the registry's
  single assignment, at a poll top — never inside a settle or
  an export, so an export always runs under exactly one plugin
  set (the same race argument round 3 pinned for profiles).
  The swap lands only when the new set's digest differs from
  the active set's, so touching a plugin file (stat moves,
  bytes identical) reloads silently. Because the content
  cache is namespaced by the active set's digest, post-swap
  exports derive under the new namespace: the shipped pin
  proves a post-swap export equals a fresh build under the new
  plugin, byte for byte, through the persisted cache.
- Announcement: `[watch] plugins reloaded:` on the watch
  stream, followed by the loader's own per-plugin lines and
  the standard trust warning (a reload executes code; it is
  announced like a load). Clearing the list announces
  "no plugins are active now" (no code was loaded, so no trust
  warning is printed for that case).
- Failure: a load error keeps the last-good set and reports
  once per distinct failure, keyed on (entries, the plugin
  files' CONTENT digests, the error text) — re-saving the same
  bad bytes moves the mtime, retries the load, and stays
  silent; a different bad edit reports again; fixing the file
  applies it and the announcement says "(recovered from a
  failed plugin load)". The session summary gains a
  `plugin_reloads` count (additive; 0 for unmanaged sessions).
- The startup load itself is unchanged and remains the
  caller's (the CLI's) job; watch manages CHANGES relative to
  that baseline. `manage_plugins=False` (library default, all
  pre-v1.0.4 callers) keeps the old behaviour bit for bit.

## Audit #1 (self-probes beyond the shipped pins)

- Item A: the dangling a<->b loop, a `.ghostslice.json` shaped
  fixture, and glob patterns (`pkgs/*`) all behave; a
  workspace-scoped CLI surface (`scan --json` -> `packages`)
  agrees with the library result. Root-through-symlink scans
  are the caller's resolved root (scan() resolves its root
  before walking) — unchanged v0.21 behaviour, not a surface
  this round owns.
- Item B: unnamed generic receivers, where-brace placement
  variants, and next-line-brace impls probed (above). A Go
  multi-line generic SIGNATURE (params over several lines,
  brace on the closing line) gets the same span treatment as a
  multi-line plain signature — parity with the pre-existing
  lite behaviour, not a new gap.
- Item C: profile reload and plugin reload landing in the SAME
  poll (profile edited to add a plugin whose file also changed)
  apply in order — profile first, then the plugin load judged
  against the new profile; a plugin failure while the profile
  itself is invalid reports only the profile failure (the
  plugin check judges the live, last-good profile, whose
  inputs did not move).

## Improve #1 (after Audit #1)

Version 1.0.4 everywhere v1.0.3 pinned it, CHANGELOG [1.0.4],
README (the watch section's restart caveat replaced by the
plugin-reload behaviour; the symbol-outline limits paragraph
now states the Go/Rust generics handling and the remaining
trait-`where` limit), ROADMAP round-4 line, plus two shipped
pins written from the Audit #1 probes (adversarial brace spans,
below) — no behavioural change beyond the WORK items.

## Audit #2 (fresh eyes)

- **Adversarial formatting vs the Go/Rust fixes** (converted to
  shipped pins): braces inside Go strings, raw strings, and
  comments leave `S.Tricky`'s span exact and the following
  function unmoved; Rust bodies containing `"}"`, `'{'`, `'}'`,
  a lifetime (`&'static str`), and a brace comment keep both
  impl spans and all method parents exact. Go type parameters
  holding a func type (`func Apply[T func(int) int]`) outline;
  Rust lifetime impls (`impl<'a> Foo<'a>`) and Fn-arrow bounds
  (`impl<T: Fn(i32) -> i32>`) name the right type — the arrow
  rule in `_strip_generic_spans` earns its keep.
- **Symlink fixtures against the remaining shared-loader
  surfaces**: export on the cyclic fixture terminates with the
  true file set; the MCP `scan_project` pin ships in the test
  file (the brief's conditional — it does share the loader).
- **Plugin swap racing a settle-window export** (shipped pin):
  a change starts its debounce window, the plugin bytes change
  inside the window, and the pending export provably runs under
  the new set (V2-only content in the bundle; the announcement
  precedes the final "bundle rewritten" line). The swap can
  only land at a poll top, and settles read the registry when
  they run — the round-3 profile race argument, re-proven for
  plugins. A `--plugin` extra-path byte edit also swaps
  (probed; same signature machinery).
- **F1 [LOW] (found here, fixed in Improve #2):** a glob member
  pattern whose literal prefix is a directory only through a
  symlink (`links/*` with `links -> pkgs`) matched nothing real
  and was reported as `missing` — the path is not missing, it
  is link-blocked. Improve #2 adds `_link_blocked_prefix`: such
  patterns now get the same "reached through a symbolic link;
  skipped" warning as literal members, and are not reported
  missing. Pinned.

## Improve #2 (after Audit #2)

F1 (above): `_link_blocked_prefix` + the shared
`_symlink_warning` in workspaces.py, with a pin; plus a pin
that deleting the profile mid-watch clears the plugin set
along with the profile (defaults name no plugins — the two
reload disciplines compose). No other changes: Audit #2 found
no over/under-reach in Items B and C.

## Final verification (after Improve #2)

- Full suite: **892 passed, 1 pre-existing skip, 9 subtests**
  (864 baseline + 28 new in tests/test_v29_polish4.py). The one
  existing pin changed is the release version pin
  (test_v25_release.py: 1.0.3 -> 1.0.4, function renamed to
  match) — the change that pin exists to track. No CLI flags
  were added or changed this round, so the completions drift
  test passes with the shipped examples untouched.
- `ghostslice secrets .`: exit 0. `ghostslice doctor .`:
  healthy (9 ok, 1 warning — the pre-existing ledger
  estimator-mix note; version 1.0.4 agrees with pyproject).
- `ghostslice lint .`: 0 errors, exactly the 5 documented
  warnings — the new code introduced none. `ghostslice calls .
  --dead`: 0 candidates.
- GhostBus demo export unchanged at 129,555 -> 45,770
  estimated tokens (test_v13 pin, in the suite).
- Dashboard page: `.innerHTML` property access still absent
  (the four `innerHTML` strings in dashboard.html are comments
  stating the rule; the v1.0.2 live-server pin passes).
- No `.ghostslice-cache` in the commit; `.ghostslice-history.jsonl`
  left unstaged, as always.

## Limitations

- Workspace detection's real-directory rule means a workspace
  member that is a symlink to a real in-root directory is no
  longer reported as a package. That matches the scanner (it
  never descends into symlinked dirs, so the member could never
  own a file), and the skip is warned for declared members —
  but a project that relied on the phantom package row in
  reports will see it disappear.
- Rust type declarations with multi-line `where` clauses are
  named but their methods are not enumerated (impl blocks with
  `where` clauses are fully handled). Go/Rust lite parsers
  remain line/brace matchers: braces inside where-clause
  const-generic expressions and type-parameter constraints
  nested deeper than one bracket level are still edges.
- Watch plugin reload re-runs the load on a stat change, which
  EXECUTES the plugin — that is the feature (it is how an edit
  takes effect), announced with the trust warning every time a
  swap actually lands. A plugin whose bytes change on every
  poll (e.g. generated into place by a build) will be reloaded
  on every change; the digest gate keeps byte-identical
  rewrites silent.
- The dashboard/CI/MCP surfaces inherit the scanner's file
  symlink policy (followed, documented since v0.21); only
  directory traversal and content serving are contained, as
  before.
