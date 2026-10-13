# G04 Audit — Config slicing: `structure` mode (v0.9.0)

Goal: a `structure` mode for YAML/TOML/JSON/SQL/shell/PowerShell
with a documented value rule (sensitive keys always placeholdered;
numbers/bools/short enum-like strings kept; everything else
placeholdered) and a scanner backstop over the output. Baseline
223 tests; build brought the suite to 267 (44 new in
tests/test_v09_config.py). GhostBus demo unchanged: 165,052 ->
53,339 (language labels only: 6 former "text" files are now
yaml x3, shell x2, toml x1; modes identical).

## Audit #1 (after build)

All findings below were reproduced with probes before being
written up (probe script exercised blank-separated lists,
indentless sequences, sensitive parents, one-line functions,
trailing comments).

### F1 [CRITICAL] Indentless YAML sequences leak a sensitive exemplar
YAML allows sequence items at the SAME indent as their parent key:
```
admin_passwords:
- first-secret-value
- second-secret-value
```
The parent key was only put on the inheritance stack when its
children were consumed by the recursive block call, which requires
child indent > key indent — false here. The sequence therefore saw
no parent key and rendered the first item verbatim. Any secret in
an indentless list under a sensitive key leaks through structure
mode. Fix: maintain a per-block key stack (pushed for empty-rest
keys whether or not recursion consumes children, popped when a
sibling at the same/shallower indent arrives) and let the sequence
parent lookup accept indent <= item indent (the owning key of an
indentless sequence sits at the items' own indent).

### F2 [CRITICAL] One-line shell/PowerShell functions keep their body
`f() { API_TOKEN=<value>; }` was kept as-is under the "one-line
functions are surface" rule, so an assignment-shaped secret inside
a one-line body reaches signatures output verbatim (probe: secret
present in output). The multi-line rule collapses bodies; the
one-line exception was the hole. Fix: one-line functions collapse
to the same header form as multi-line ones (`name() { # ... }`)
in both shell and PowerShell. The build's one-line test is
updated to pin the collapsed form (this goal's own test, changed
for a security fix — no baseline test touched).

### F3 [MEDIUM] YAML list-of-maps under a sensitive key renders values
`credentials:` with a list of maps rendered the exemplar's values
(`user: bob`, `role: admin`) because each item key was judged on
its own name only. JSON replaces a sensitive key's container
wholesale; YAML should match. Fix: when the sequence's parent key
is sensitive, the exemplar collapses to a bare placeholder item
(plus the usual count line).

### F4 [MEDIUM] Blank lines between YAML list items break collapsing
Item-span and sequence gathering stopped at blank entries, so
```
features:
  - auth

  - billing
  - reports
```
rendered as two sequences (auth; billing + "+1 more") — wrong
exemplar set and wrong count. Blank (and comment) entries belong
to the current item span / sequence until a real entry decides
otherwise. Fix span and sequence gathering to carry tentative
blank/comment entries and trim them at span ends.

### F5 [MEDIUM] TOML trailing comments corrupt arrays and strings
`ports = [8001, 8002] # ports` rendered as `ports = []` (the
array renderer sliced to the last character, which was comment
text), and `name = "ghostslice" # note` placeholdered the string
(the trailing comment broke the quote check). Fix: strip the
trailing comment with a quote-aware scan before any value branch.

### F6 [LOW] Dashboard per-file mode dropdown lacks the new mode
dashboard.html hardcodes ['full','signatures','interfaces',
'strip-tests','exclude'] for the per-file mode <select> (the
server itself validates against MODES dynamically, and `headings`
was already missing from the same list). Add 'structure' and
'headings' to the dropdown so the dashboard can actually request
the modes the server accepts.

### Categories audited with no findings
- Value-rule false negatives on compound names: db_pass,
  apiToken, client-secret, aws_secret_access_key, session_id,
  my_jwt all flag; monkey/keyboard/tokenizer/author/passage do
  not (segment matching, pinned by unit tests both directions).
- Planted secrets in every format (structure AND signatures):
  YAML map/list/block-scalar/wrapped-continuation, TOML plain/
  inline-table/multiline-string, JSON plain/exemplar/nested,
  SQL INSERT values, shell assignment/command-line — all absent
  from output (the wrapped-continuation case is caught by the
  scanner backstop, which is exactly what it is there for).
- SQL comments preserved verbatim: parity with full mode (a
  comment is not made more visible by structure mode); CREATE
  statements are verbatim by design, same reasoning. INSERT
  ... SELECT and string-semicolon splitting behave.
- Shell function with the brace on the following line: the body
  is processed as top-level lines (keeps more — assignments in
  the body render under the value rule — never less). Matches
  the parser-lite convention of every other language here.
- YAML `--- {inline}` document content and heredoc openers
  inside quoted shell strings: known lite edges, degrade to
  keeping more; the backstop still applies to the output.
- JSON duplicate keys: json.loads keeps the last, same as any
  JSON consumer; structure output is valid JSON (round-trip
  asserted in tests via the exemplar shapes).
- Wiring: fit's _RUNG gained "structure" (a profile-set structure
  mode would previously KeyError under --fit); exporter estimate
  path, MCP enum and server validation all read MODES dynamically;
  export defaults unchanged (config files stay full unless a
  profile/--mode opts in — GhostBus modes identical).

## Improve #1 (fixes applied, suite 267 -> 273)
- F1: per-block key stack in _yaml_block (push on empty-rest key,
  pop on sibling/shallower entries); _yaml_sequence parent lookup
  now accepts indent <= item indent. Regression tests: indentless
  sensitive list placeholdered; indentless plain list collapses.
  Note: the first attempt at the pop rule had the item/key limits
  inverted (items popped same-indent keys, losing the parent
  again); the F1 regression test caught it immediately and the
  limits were swapped to the documented form.
- F2: one-line functions collapse in slice_shell and
  slice_powershell; the build's one-line shell test now pins the
  collapsed form, plus a leak test with a planted token.
- F3: sensitive parent key collapses the YAML sequence exemplar
  to a placeholder item. Regression test added.
- F4: YAML item spans and sequence gathering carry blank/comment
  entries tentatively and trim trailing ones. Regression test:
  blank-separated list collapses to one exemplar + count.
- F5: quote-aware trailing-comment strip in slice_toml before
  value branching. Regression tests: array and string cases.
- F6: dashboard mode dropdown gains 'structure' and 'headings'.

## Audit #2 (of the build + Improve #1 fixes)

Fresh probes against the fixed code (nested list items, quoted
colon keys, escaped quotes, SQL comment-like strings, nested
map-then-list, here-string variants):

### G1 [MEDIUM] PowerShell here-string opener with a trailing comment leaks its body
`$Body = @" # comment` did not match the exact-opener check, so
the here-string body fell through to top-level processing and a
body line like `$Fake = 1` rendered as a real assignment. No
secret leak (body values still pass the value rule if rendered),
but string content must never be re-interpreted as code — the
same class of bug as shell heredocs, which were handled. Fix:
accept an opener followed only by whitespace / a comment.

### G2 [LOW] Flow-style YAML list items render approximately
`- {name: alpha, port: 8001}` rendered as `- {name: "…"` (the
flow text was fed to the block renderer, which placeholdered the
rest of the line and dropped the closing brace). Safe direction
(nothing leaks) but needlessly lossy when _flow_render already
exists. Fix: flow-style first items render through _flow_render
with the sequence's parent key as context, joining span lines
when the flow spans lines.

### Categories re-checked with no findings
- Nested sequences (`- - 1`) collapse correctly at both levels.
- Quoted YAML keys containing a colon (`"api:token":`) are
  parsed as one key and placeholdered on the token segment.
- TOML strings with escaped quotes and `#` inside survive the
  F5 comment stripper intact (placeholdered only by the value
  rule, following lines untouched).
- SQL: `--` inside a quoted INSERT value is not mistaken for a
  comment; the row count stays correct.
- Stack discipline after the F1 fix: sibling keys pop the stack
  correctly (nested map followed by a list renders with the
  right parent), and the F1 regression caught the inverted
  limit before it could ship (see Improve #1 note).
- JSON homogeneous-dict collapse: only above 20 entries and
  only when all values share one category; heterogeneous maps
  render in full. The sensitive-key check runs before the
  collapse, so a sensitive name is never exemplar-rendered.

## Improve #2 (fixes applied)
- G1: PowerShell here-string opener accepts trailing whitespace
  or a comment; regression test added.
- G2: flow-style YAML sequence items render via _flow_render;
  regression test pins `- {name: alpha, port: 8001}`.
- Added a wiring test: profile-set structure mode combined with
  export --fit completes (fit's rung table knows `structure`).

Postscript (pre-commit gate): the first final `ghostslice
secrets .` run flagged five lines in the new test file itself —
fixture values written as plain literals. They were rewritten
as fragment-assembled constants / @@ markers substituted at
runtime (the same technique as earlier goals' tests), and the
scan now exits 0 with the suite unchanged.

Final state: 276 tests passed (223 baseline + 53 new: 44 build,
6 improve round 1, 3 improve round 2), version 0.9.0,
`ghostslice secrets .` exits 0, GhostBus demo unchanged
(165,052 -> 53,339; scanner language labels only). Committed
locally; push/release is the parent's step.
