# G14 Audit — Python call graph + dead-function detection (v0.19.0)

Goal: a symbol-level call graph for Python (AST-based): `ghostslice
calls` with caller/callee listings and a fan-in ranking, plus
dead-function candidates fed into the `scan` / `graph` prune
recommendations as kind "dead-symbol". Edges are classified exact
(same file / `self.` / resolved base / direct import evidence),
heuristic (bare name matched across modules with no import
evidence), and attribute (`anything.name(...)` fans out to every
project method of that name). Baseline 555 tests; build brought
the suite to 583 (28 new in tests/test_v19_callgraph.py).

Design summary: new module callgraph.py. Symbol tables come from
symslice's Python outline (same names/spans `ghostslice symbols`
prints; redefinitions grouped — the last definition's span is the
live one). Import resolution reuses graph.py's module mapping
(`_py_module_base` + its candidate shape). References count as
well as calls (callbacks, dict/list values, defaults, decorator
expressions, base classes). Roots: module top levels, profile
entry points (full trust) and heuristic entry files (only a
function named `main`), [project.scripts] targets, `__all__`
names, test files + conftest.py, framework-decorated functions,
and methods of classes extending non-project bases. Dunders are
never candidates; unparseable files are skipped, never judged.
graph.recommendations itself is unchanged — lint consumes it and
gains nothing this round; the CLI merges dead-symbol entries
into the scan/graph surfaces only.

## Audit #1 (after build) — dogfood on this repo + fixture battery

The build's first act was running `calls --dead` on GhostSlice
itself: **44 candidates**, and reading them was the audit.

### F1 [HIGH] Instantiation never reached `__init__` — whole subtrees flagged
38 of the 44 candidates were this module's own symbols
(`_Walker.visit`, `CallGraph._build`, `_collect_file_facts`, the
dataclasses `_Sym`/`_ClassInfo`, ...), all with healthy fan-in.
The edges existed; reachability broke at one joint: `CallGraph(...)`
edged to the *class* symbol, but `__init__` — the method that
calls `_build`, which calls everything else — had no incoming
edge, so the entire downstream subtree read as unreachable.
Fix (Improve #1): a resolved call edge to a class also edges to
its `__init__` (its own, or an inherited project one via the
base-class resolver). The same gap existed for `cls()` inside a
classmethod: the walker now tracks each function's first argument
and classmethod-ness, so `cls()` is an instantiation and
`cls.m()` a call on the enclosing class. Exact edges on this
repo: 1,641 → 2,388.

### F2 [HIGH] Framework-invoked protocol methods flagged
`server.make_server.Handler.do_GET` / `do_POST` / `log_message`
were candidates: `Handler(BaseHTTPRequestHandler)` is invoked by
the stdlib server machinery, never by project code — and
`_State.scan_payload` / `mode_tokens` hung off those handlers, so
they flagged too. Fix (Improve #1): the methods of any class
extending a base that does not resolve to a project class are
roots (the external base's protocol is the caller). A genuinely
dead helper on such a class now gets a pass — the conservative
direction, stated in the README.

### F3 [MED] Heuristic entry files rooted everything in them
The first root rule ("entry-candidate files root their top-level
callables") nominated `pkg/app.py` in the test fixture — `app.py`
is in the prune engine's basename heuristic — and rooted every
function in it, hiding the deliberate getattr candidate. app.py
is half the world's Flask apps; most of its functions are not
entry points. Fix (Improve #1): two trust levels — profile-declared
entry files root their top-level callables; heuristic files root
only a function actually named `main` (their `__main__` blocks
already contribute module-level edges).

### F4 [MED] src-layout absolute imports did not resolve
`ledger.read_records` and `selection.select_for_task` flagged
because their only callers are tests importing
`ghostslice.ledger` / `ghostslice.selection`, and graph.py's
root-relative mapping looks for `ghostslice/ledger.py`, not
`src/ghostslice/ledger.py`. Fix (Improve #1): `_module_file`
gains a unique-suffix fallback (exactly one scanned file ending
with the module path wins; ambiguous → unresolved). Reading the
three names by hand: read_records is a public helper whose
in-src caller disappeared in the G9 refactor (summary/analytics
use `_parse_file` now) — "dead inside src, alive as API" is the
honest verdict; select_for_task is the same shape (src uses
select_for_task_breakdown). The third, `selection._any_keyword_
part_in`, is a TRUE positive: unused inside src since G2's gate
change, kept alive only by its direct unit test — which, once
its import resolves, is a real caller by the tool's rules.

### F5 [LOW] The unresolved counter drowned its own signal
4,249 of 9,190 call sites counted "unresolved", almost all of
them method calls on stdlib/external objects (`x.read_text()`)
whose names simply match no project method. Those are external
calls in every practical sense; the residue now counts as
external, and "unresolved" means what a reader expects (local
callables, subscripts, getattr — 17 on this repo).

### Fixture-side correction (the engine was right)
The first fixture run flagged `use_module_alias` and `compute`:
nothing in the fixture called them. They were edge-assertion
vehicles I forgot to wire in — wired into `script_entry`, and
their callee `doubler` came alive with them.

Post-Improve-#1 state: this repo reports **0 dead candidates**
(exact 2,388+, heuristic 0, unresolved 17); the fixture dead set
is exactly the six genuinely dead symbols (one per designed
class: dead function, dead lambda, dead method, getattr-only
function, and a mutually-recursive pair — direct self-recursion
is exempt by rule, clusters are reachability's call).

## Audit #2 (after Improve #1) — dispatch-pattern battery

Fresh probes (each a pattern the first battery didn't cover):
super() chains, inherited methods via a subclass's `self`,
property getter/setter pairs, `functools.partial` and
signal-style `connect(...)` hand-offs, dict-table method
references, star imports, conditional (if/else) definitions,
async call chains, chained calls `get().m()`, classes extending
external bases, and a local (non-imported) decorator — which
correctly does NOT root its function (`decorated_but_unused`
flagged; the decorator itself stays alive by reference). Two
initial probe "failures" were probe-side: the functions were
genuinely uncalled as written; corrected probes pass.

### F6 [HIGH] Template-method overrides flagged — polymorphic fan-out missing
`Template.__init__` calls `self.hook()`; the resolver made an
exact edge to `Template.hook` only, so `Impl.hook` — the
override that actually runs for `Impl()` — was a candidate.
A `self.` call dispatches on the runtime type; the exact edge
was half the truth. Fix (Improve #2): `self.m()` / `cls.m()`
also fan out (kind "attribute") to same-named methods in
project subclasses of the enclosing class, via a subclass index
built from resolved project bases. `super()` stays exact-only
(super dispatches strictly upward). Regression tests:
TestDispatchPatterns (7 tests) pins the whole battery, F6
included.

### Checked, no defect
- Conditional definitions group into one symbol (last span
  wins), called → alive; star imports degrade to heuristic
  name matching, never silence.
- The repo dogfood stayed at 0 candidates after the fan-out
  (fan-out added edges only inside real hierarchies), and the
  fixture dead set did not move.
- Fan-in honesty: attribute edges are name-based, so a method
  named like a common stdlib method collects unrelated fan-in
  (this repo: a test helper named `get` shows fan-in 230 from
  dict `.get(` calls). Documented as a ranking hint, not a
  verdict; dead detection is unaffected because attribute
  edges only ever *add* reachability.

## Limitations (documented in README)
- String-based dispatch is invisible by design: `getattr(x,
  "name")`, string registries, and entry-point-by-string wiring
  leave no edge; such a function is flagged, under the honesty
  line. Monkeypatching, `exec`/`eval`, dynamic class creation,
  and metaclass `__call__` are likewise invisible.
- Import resolution is graph.py's root-relative model plus a
  unique-suffix fallback for src layouts; ambiguous suffixes
  and `import *` bind no names (bare calls then fall back to
  heuristic name matching).
- Attribute fan-in/fan-out is name-based across the project —
  deliberately conservative in both directions.
- A mutually-recursive cluster with no root caller is flagged
  even though its members call each other; only a direct
  self-edge exempts.
- Non-Python files keep file-level behaviour only.

Final state: 590 tests passed (555 baseline + 35 new: 28 at
build, +7 dispatch-pattern regressions with Improve #2); the
555 existing tests are unweakened; `ghostslice secrets .`
exits 0; version 0.19.0.
