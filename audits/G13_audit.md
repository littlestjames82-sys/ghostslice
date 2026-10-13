# G13 Audit — Symbol-level slicing (v0.18.0)

Goal: `ghostslice symbols` outlines for every sliced language, and
`export --symbols` (plus MCP `export_bundle` symbols) shipping
requested symbols WITH bodies plus signature context — bare names,
`Class.method` qualified names (suffix-matched), `file.py:name`
scoping, globs. Ambiguity includes all matches and is printed; an
unmatched entry is a hard error with near-miss suggestions before
anything is written. Baseline 525 tests; build brought the suite
to 552 (27 new in tests/test_v18_symbols.py).

Design summary: new module symslice.py. Python outlines/rendering
are ast-exact and reuse the signatures renderers (`_func_signature`
/ `_class_signature`); lite outlines reuse the slicer's own
declaration regexes and the string/comment-aware brace matcher
(no second parser); lite rendering is a generic line-range walker
over outline spans (kept = verbatim, functions collapse to a
signature line, declaration types stay whole — both exactly the
signatures conventions). Resolution matches pattern == qualified
or bare name or a dotted/`::` suffix of the qualified name.

## Audit #1 (after build) — self-attack battery

Battery (beyond the unit tests): deep nesting (class inside a
method inside a class), kept class attributes with multi-line
values, a 30-item module constant kept and unkept, unparseable
Python (fallback outline), consecutive TS arrows (span swallowing),
braces inside strings and `${}` template bodies, TS getters/statics,
C++ in-class bodies and template functions, Go interface selection,
a secret inside a NON-selected body (must not ship even without
--redact), decorated classes and async methods, Scala 3
significant-indentation defs, plus integration probes:
exclude-secrets vs a symbol match, symbols in test files, empty
spec, profile mode vs symbols, duplicate conditional definitions,
and a dogfood export of this repo (`build_bundle`,
`resolve_symbol_selection` -> 9,115 sliced estimated tokens,
validator OK).

### F1 [HIGH] Conditionally-defined Python symbols vanish from the slice
The outline (ast, descending into compound statements) finds
`def go()` under a module-level `if/else`, resolution matches it,
the file ships in mode `symbols` — and the renderer emitted only
the imports: `_slice_python_symbols` walked `tree.body` statements
and had no branch for `ast.If`, so both bodies were silently
dropped. The export claimed the symbol and shipped neither body:
exactly the "typo silently exports less context" failure class,
except the "typo" was ours. Same hole in class shells (a method
under `if TYPE_CHECKING:`) and function shells.
Fix (Improve #1): all three Python renderers recurse into
compound statements via a shared `_compound_stmts` helper that
also unwraps except handlers and match cases: module scope
(`_render_py_module_stmt`), class bodies, and function bodies.
Kept conditional defs ship verbatim (source indentation, the
`if` line itself dropped — the signatures philosophy); unkept
ones signpost as signature lines. Regression tests:
conditional if/else defs kept + signposted, TYPE_CHECKING method
in a class shell, try/except and match-case probes in the battery.

### F2 [LOW] Fit/secrets/profile interplay — verified, no change
Probes confirmed the documented precedence: --exclude-secrets
excludes a matched file (report gains `excluded_by_secrets`, CLI
prints it); symbols beat a profile per-glob mode (explicit user
selection, same rule as `selections`); profile entry points keep
their mode; `--symbols` + `--fit` raises before scanning; a
matched test file ships symbols-mode like any explicit selection.

### Checked, no defect
- No context leakage: in every battery case a non-requested body
  marker is absent and the signature signpost present, including
  the sibling-class case and the collapsed-body secret case.
- TS spans: consecutive arrows stay separate; a body containing
  `"}{{{"` and a `${}` template does not corrupt spans (the
  shared brace matcher is string/interpolation aware).
- C++: in-class declarations and out-of-line definitions are
  distinct symbols (`Box::open` inline body kept correctly,
  `Store::total` out-of-line kept, sibling collapsed via
  `_c_sig_text`); template head lines belong to the span.
- Java K&R (brace on the next line) methods are not outlined —
  the same documented limit `_JV_METHOD_RE` imposes on the
  signatures slicer; consistent, not a divergence.

## Audit #2 (after Improve #1) — fresh probes

Compound-recursion side effects (try/except defs, match-case
defs — both kept), C# class inside a namespace, TS generic class
`Box<T>`, Swift extension methods, Kotlin `object` members,
file-scoped globs in resolution (`src/*.py:login`), anthropic-xml
wrapper validation on a symbols bundle, Rust trait default bodies
and PHP interface methods (declaration-type selection ships the
whole type), and a full `symbols` listing over this repo
(1,490 symbols, 50 files, no crash; single-file project roots OK).

### F3 [MED] Kotlin/Swift properties and PHP fields missing from outlines
Cross-checking against `selection.symbols_for_source`: task
selection counts Kotlin/Swift top-level `val`/`var` and (via the
signatures output) class properties as symbols, and the
signatures slicers keep them — but the new outlines had no
property symbols at all, so `--symbols "VERSION"` on a Kotlin
file errored as unknown for a symbol the tool elsewhere treats
as a definition.
Fix (Improve #2): `_extra_region` records cfg["prop"] lines as
symbols (kind constant at top level, attribute inside a type;
name from per-language patterns — PHP `$name`, Kotlin/Swift
`val/var/let name`), including computed properties with brace
bodies. They render verbatim (data is always-context), which
also puts class fields into shells by name instead of only by
the interior-line heuristic. Regression test:
test_extra_language_property_symbols.

### Checked, no defect
- Compound recursion did not change plain files: full suite
  stayed green through both improves (525 existing tests
  unweakened), and the Audit #1 battery re-ran clean.
- Prefix collisions: `_has_kept_descendant` requires a `.`
  boundary (`Auth.` does not claim `AuthExtra.login`); per-file
  keep sets mean a foreign name in a direct `slice_with_symbols`
  call just renders signatures, never another file's body.
- Manifest/validator: symbols bundles validate (hashes, totals,
  wrapper mirrors) on claude-code, json, and anthropic-xml
  presets; totals ordering symbols < signatures < full holds on
  the fixture project.

## Limitations (documented in README)
- Lite outlines are top-level definitions plus class members:
  nested functions are Python-only. Constructors are not
  selectable in lite languages; C# namespaces do not prefix
  qualified names; Go grouped `type ( ... )` declarations are
  not outlined; Kotlin/Swift single-expression bodies continuing
  by indentation count only their first line.
- A C++ in-class declaration and its out-of-line definition are
  separate symbols; selecting the definition's spelling
  (`Store::total`) is what ships the body.
- Conditionally-defined Python symbols render without their
  `if`/`try` wrapper lines (verbatim segments keep source
  indentation) — the signatures philosophy, stated in the audit.
- Declaration types (interface/trait/protocol/struct/enum) ship
  whole when any of their methods is selected — they are
  declaration surface, exactly as in signatures mode.

Final state: 555 tests passed (525 baseline + 30 new: 27 at build,
+2 regression tests with Improve #1, +1 with Improve #2); the 525
existing tests are unweakened; `ghostslice secrets .` exits 0;
version 0.18.0.
