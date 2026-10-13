# G03 Audit — C, C++, Scala parser-lite slicers (v0.8.0)

Goal: C (.c/.h), C++ (.cpp/.cc/.cxx/.hpp/.hh), and Scala
(.scala/.sc) slicers in the established parser-lite pattern:
signatures + interfaces + strip-tests, wired through the scanner,
exporter SLICABLE, the `slice` CLI, and the G2 symbol-extraction
fallback. Baseline 196 tests; the build brought the suite to 216
(20 new in tests/test_v08_langs2.py).

## Audit #1 (after build)

Probed beyond the golden samples: out-of-line C++ definitions,
Allman braces with comments, template angle brackets, Scala type
equality, C function pointers.

### F0 [CRITICAL] Qualified and pointer-attached function names never match
`_C_HEAD_RE` splits a head as *(modifiers) (prefix + whitespace)
(name)*. Two ordinary shapes have no whitespace before the name:
`int Store::total() const {` (the `::` binds the name directly) and
`struct Money *make_money(...)` / `char* get_name()` (the `*` binds
to the name). For both, the regex cannot match, so the definition
is not recognised at all: in signatures mode the function VANISHES
and its body lines leak as stray top-level "statements" (probe:
slicing an out-of-line ctor + method produced just `return
total_;`), and a C function returning `struct Money *` fell through
to the type-block path and was emitted with its body in full.
Out-of-line member definitions are the dominant shape in real C++,
so this is the build's headline defect. Fix: restructure the head
regex so the name is the identifier immediately before the
parameter `(`, with everything before it captured as a type-like
prefix; validate the prefix in code (no `(`, `)`, `{`, `;`; first
word not a control keyword; the existing `=`-before-`(` and
typedef guards unchanged). Apply the same restructure to the G2
`_C_SYM_RE` in selection.py, which has the identical flaw against
our own signatures output.

### F1 [MEDIUM] Definitions continued past the `)` line are dropped
Even with F0 fixed, `_c_func_head` only accepts a body brace on the
`)` line or alone on the next line. An out-of-line constructor with
a multi-line initializer list (`Store::Store(name)\n : name_(name)
{`) or a trailing return type on its own line returns None and the
definition is skipped. Fix: when the `)` line ends without `;` or
`{`, scan up to 4 further lines for a `{` that precedes any `;` on
its line (ctor-init lists and trailing returns have no `;` before
the brace; K&R parameter declarations do, and stay a documented
non-goal).

### F2 [MEDIUM] `_mask_quotes` is comment-blind
`_find_block_brace`, `_stmt_end`, and the head scans trust the
masked line, but the masker only blanks string/char literals.
Punctuation inside comments misleads them: an Allman class whose
declaration line carries a `// ...;` comment is misread as a
forward declaration, so the class is never recursed (probe: header
kept, `public:` and the closing brace lost, method emitted at top
level). A `(` inside a comment likewise skews head paren counting.
Fix: mask `//` to end-of-line and same-line `/* ... */` spans in
`_mask_quotes` (string state takes precedence, so `http://` inside
a literal is safe; multi-line block comments are masked only on
their opening line — the brace matcher itself stays comment-aware
across lines, and the residual risk is noted).

### F3 [LOW] C++ raw-string delimiter scan accepts a quote
The delimiter scan in `_brace_end` stops on space, `)`, or `\` but
not on `"`. An identifier ending in `R` followed by a normal string
(`R"abc"`) and a `(` later on the line with no intervening space
could be misread as a raw string. Real raw strings are unaffected
(their delimiter cannot contain a quote by definition). Fix:
exclude `"` from delimiter characters.

### F4 [LOW] Scala body-`=` detection is not standalone
`_scala_def` records the first `=` at paren depth 0 as the body
equals, but `=:=` (type equality), `==`, `>=`, `<=`, `!=` also
contain one. A bodied def whose signature uses `=:=` gets its
signature truncated at the `=:=` (probe inside a trait was masked
because traits are kept in full; a class def shows it). Fix: only
a standalone `=` counts (neighbours not in `=< >!:` and the next
char not `>`).

### F5 [LOW, DOCUMENTED] Known-shape limits confirmed acceptable
- One-line class bodies (`class Foo { int x; };` on a single line)
  lose their members: the class region is empty. Identical limit
  in the v0.3 Java/C# lite slicers; noted in the C++ section
  comment and README.
- `.h` is C by scanner convention: a C++ class in a `.h` header
  slices by the C rules (methods found, class context lost).
  Documented in README; `.hpp`/`.hh` get the full C++ treatment.
- K&R parameter declarations between `)` and `{`, declarations
  with the return type alone on its own line, `extern "C"` wrapper
  lines (functions inside are found), C++ concepts/requires.

### Categories audited with no findings
- Template angle brackets: `template <int N = (4 > 2 ? 1 : 0)>`
  heads, `std::vector<std::vector<int>>` return types, and
  `operator<` all slice correctly (probe P4) — the head machinery
  never counts angle brackets, and the template-head gatherer's
  `<`/`>` count is quote-masked.
- C preprocessor: `#define OPEN {`, an in-body `#define` with a
  lone brace, and a multi-line backslash macro neither corrupt
  brace counting (preprocessor lines are skipped by `_brace_end`
  for c/cpp) nor lose surrounding functions.
- Digit separators and char literals: `1'000'000` in a body and
  `'{'` / `'}'` char literals do not disturb body skipping; the
  G2 symbol gate test caught a real regex bug during the build
  (two-word return types), fixed before this audit.
- Scala: nested block comments, triple-quoted strings, and
  s-interpolation with a nested map literal inside a class body
  all slice soundly; Scala 3 indented classes/defs slice by the
  indentation fallback and an indented trait is kept in full
  (the documented keep-more degradation).
- Function-pointer typedefs are not mistaken for functions
  (the `(*name)` guard). A function *returning* a function pointer
  (`int (*handler_for(int))(int) { ... }`) is likewise not matched
  as a head: its declaration line is skipped and its body lines
  can leak as statements in signatures mode (probe P5) — an
  accepted lite limit, same family as F5, not corruption of
  surrounding declarations (the next function slices cleanly).
- gtest TEST/TEST_F blocks in a non-test-named file are stripped;
  *_test.cpp / *Spec.scala files are dropped wholesale by
  slice_source via the scanner's test detection, as designed.


## Improve #1 (fixes applied, suite 216 -> 221)

- F0: `_C_HEAD_RE` restructured — the name is the identifier
  immediately before the parameter `(` and everything before it is
  a type-like prefix (`int Store::`, `struct Money *`, `char*` all
  work now); `_c_func_head` validates the prefix (first word not a
  control keyword, existing `=`/typedef/`(*` guards unchanged).
  `_C_SYM_RE` in selection.py restructured identically. Regression
  tests: out-of-line definitions, pointer-attached returns, symbol
  extraction for both shapes.
- F1: `_c_func_head` forward-scans up to 4 lines past the `)` line
  for a body brace that precedes any `;` (ctor initializer lists,
  split trailing returns). Probe P1 now produces both signatures.
- F2: `_mask_quotes` also masks `//` line comments and same-line
  `/* ... */` spans (string state wins). Probe P2 now keeps the
  class header, `public:`, members, and the closing brace.
- F3: raw-string delimiter scan in `_brace_end` also excludes `"`.
- F4: Scala body-`=` must be standalone (neighbours not in
  `=<>!` / `=:>`); a bodied class def using `=:=` keeps its full
  signature (regression test).
- F5: documented only, no code change (see Audit #2 for one
  addition to this family).


## Audit #2 (of the build + Improve #1 fixes)

Fresh probes aimed at the fixes themselves: false-positive shapes
for the restructured head regex, split declarations, template
one-liners inside namespaces, comment openers inside string
literals, and the Scala `=` family.

### G1 [MEDIUM] Split declarations ending on a later line still broke
`virtual double area() const` with `= 0;` on the next line, a
prototype followed by an `__attribute__((...));` line, and a split
trailing return all share a shape the F1 scan rejected: the head
stops at the `)` line, the continuation was then emitted as a
stray statement (`        = 0;` appeared as a class member and
`area()` vanished). A declaration's parameter list is always
terminated by `{` or `;`; when neither is on the `)` line, the
first of them on a following line (within the scan window) IS the
terminator. Fix in Improve #2: the forward scan returns a
prototype whose head runs to the `;` line. Side effect, accepted:
a K&R definition's first parameter-declaration line ends with
`;`, so a K&R definition is now read as a prototype (head kept,
body not stripped) instead of vanishing — K&R stays unsupported,
documented as such.

### G2 [REVIEWED, SOUND] F0/F1 false-positive sweep
Namespace-scope globals and initialisers stay statements, never
heads: `Store global_store(5);` (bare-name guard), `int y =
compute(3);` and `unsigned mask = (1 << 3);` (`=` cannot appear
in a head prefix). A one-line template function inside a
namespace slices correctly. A `"/* not a comment"` string
literal is not masked as a comment (string state wins in
`_mask_quotes`). Scala: defaults with `=` inside parens, `==` in
bodies, and same-line `= expr` defs all still slice correctly
after the F4 guard.

### G3 [REVIEWED, ACCEPTED] Commented-out code can resurface
A `def`-shaped line at column 0 inside a multi-line `/* ... */`
comment (C++: a declaration-shaped line) can be matched by the
region scans, which read raw lines like every other lite slicer
in this codebase. The failure mode is keep-more (a phantom
signature in the output), never corruption of real declarations
around it. Accepted as a family trait of the lite approach; the
brace matcher itself remains fully comment-aware.

### G4 [REVIEWED, SOUND] Fix interactions
- The F1 forward scan and the new G1 prototype scan share one
  loop and one window (4 lines); a `;` inside a comment on a
  continuation line cannot terminate a head early because the
  scan reads masked lines (F2).
- `_c_head_end` and `_c_sig_text` already parameterise on
  `head_end`, so split prototypes join their lines with no
  further changes; `strip-tests` consumes the same head shape.
- No other callers of `_mask_quotes` exist outside the v0.8 code
  (grep-verified), so the F2 comment masking cannot regress the
  v0.3/v0.5 languages; the full suite confirms it (196 pre-G3
  tests green at every step).

## Improve #2 (fixes applied, suite 221 -> 223)

- G1: the `_c_func_head` forward scan returns a prototype whose
  head ends at the first following line carrying a `;` before
  any `{`. Regression tests pin split `= 0;`, split
  `__attribute__`, and split trailing-return declarations, plus
  the globals-are-not-heads sweep from G2.
- Docs: the C/C++ section comment now states the K&R behaviour
  precisely (read as a prototype, body not stripped).

Final state: 223 tests passed (196 baseline + 27 new across the
build and both improve rounds), version 0.8.0, `ghostslice
secrets .` exits 0. Committed locally; push/release is the
parent's step.
