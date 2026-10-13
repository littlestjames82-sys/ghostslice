# G06 Audit — Context lint (v0.11.0)

Goal: `ghostslice lint` rule engine (L001-L010) over the exporter's
own mode resolution, with profile tuning, exit codes, dashboard
/api/lint and an MCP lint_project tool. Baseline 293 tests; build
brought the suite to 332 (39 new in tests/test_v11_lint.py).

## Build notes (decisions taken)

- Mode resolution was extracted from build_bundle into
  exporter.resolve_modes and is now shared by build_bundle,
  estimate_context_tokens and lint — the spec's anti-divergence
  requirement is met structurally, and a test pins lint's payload
  modes equal to a real bundle manifest's modes on a profiled
  fixture.
- Exit contract, decided as the spec directed: exit 1 only on
  error-severity findings by default; --strict promotes warnings
  to failure; 2 for config/usage errors. Info findings never fail.
- Totals never double-count: flagged_tokens unions distinct files;
  potential_savings takes the max saving per file.

## Audit #1 (after build)

### F1 [LOW] L004 exact-duplicate message names the wrong "keep" file
For an exact group, the rule flags included copies after the first
INCLUDED one, but the message says "exact duplicate of
group['files'][0]" — the first file in the group even when that
file is itself excluded and another included copy is the one
actually carrying the content in context. Savings math is right
(the flagged copy is redundant given the first included copy);
only the named reference is wrong. Fix: name the first included
copy as the keep reference.

### F2 [REVIEWED, SOUND] The L003 duplicate-skip relies on reason-string prefixes
recommendations() also emits duplicate-derived candidates; L003
skips them by the "exact duplicate" / "near-duplicate" reason
prefixes so L004 owns them. The strings are produced in exactly
one place (graph.py) and the prefixes are pinned by the graph
tests plus the L004 fixtures. A file that is BOTH unreachable and
a duplicate still gets an L003 (unreachable) and an L004 finding —
two distinct problems with union-counted tokens, not a double
report of one problem. Kept.

### F3 [REVIEWED, BEHAVIOUR CHANGE NOTED] estimate_context_tokens now validates modes
The resolve_modes extraction means an unknown profile mode raises
ValueError in estimate_context_tokens (check-budget, MCP
estimate_cost) where the old inline copy passed the bogus mode to
the slicer. build_bundle always raised; the surfaces now agree.
Strictness is the correct direction for a config typo. Existing
tests cover both callers; no test relied on the lax path.

### F4 [LOW, known cost — assigned to G15] Duplicate detection runs twice per lint
lint_project calls recommendations() (which runs find_duplicates
internally) and then find_duplicates() again for L004 — the same
pairwise pass the dashboard's _State already duplicated before
this goal. Correctness unaffected; on very large trees it is real
time. The fix (recommendations accepting precomputed dups) is a
graph.py API change deliberately left to G15, the performance
goal, rather than bundled into a lint feature.

### F5 [REVIEWED, SOUND] L006 fires on compact data files, by design
Self-lint (below) flags both prices.json copies: single-line-ish
compact JSON, avg line 857 chars. That IS the spec'd minified
signature ("avg or p95 line length over threshold"), the rule is
warn-severity and detection-only, and exempting .json would hide
minified JSON bundles, a genuine waste class. The threshold is
profile-tunable (line_chars). Kept; the self-lint report calls it
out as a true-shape, low-stakes finding.

### F6 [REVIEWED, SOUND] L007 prose false-positive class
A doc whose first 12 lines say "automatically generated" at full
mode will warn. That is the documented trade of a header-marker
heuristic: warn severity, concrete action, and the header window
keeps body mentions silent (pinned by the beyond-header test).
Kept.

### F7 [INFO, no findings] Surface consistency
CLI text/JSON, /api/lint and MCP all return lint_project's payload
(the dashboard test and CLI test assert findings/counts equality
against the engine; MCP adds only the in-band exit_code, since a
stdio tool has no process exit). Severity stamping happens once,
in lint_project, from effective_config — no surface re-derives it.

### F8 [INFO, no findings] Config validation hunt
Unknown rule id, unknown severity, typo'd option name, string or
boolean or non-positive option values, a non-object lint section,
and a null rule entry all raise ValueError at profile load (tests
pin each); the fraction range (0, 1] is validated in
effective_config and surfaces as CLI exit 2 (test pins). The
shorthand string form ("off") normalises identically to the
object form.

### Self-lint at build time (ghostslice lint on this repo)
4 findings, 0 errors, exit 0 — all true shapes, none fixed in code
(they are the linter working on real data):
- L004 prices.json vs src/ghostslice/prices.json exact duplicate
  (379 est. tokens): INTENTIONAL — the root copy is the editable
  source, the package copy ships in the wheel (README documents
  the pair). Justified, not a defect.
- L006 on both prices.json copies: compact JSON data, avg line
  857 chars (see F5). Justified as designed behaviour.
- L006 on tests/fixtures/calibration/minified.sample: a minified
  fixture doing exactly what it exists to do. True positive.

## Improve #1 (fixes applied)
- F1: L004 exact findings now name the first INCLUDED copy as the
  keep reference ("exact duplicate of <first included>"), with a
  regression test where the group's first file is excluded.

## Audit #2 (of the build + Improve #1 fixes)

### G1 [LOW] CLI print duplicates the token cost for most rules
_print_lint appends "(est. N tokens)" after every message, but
most rule messages already state their token count in prose —
self-lint output reads "(379 estimated tokens) (est. 379
tokens)". Three rules (L003, L005, L007) state no count and rely
on the suffix. Fix properly: put the count in those three
messages and drop the printer suffix, so the message is the
single source of the number on every surface.

### G2 [LOW] L006 message overclaims "minified" for prose/data
On GhostBus the rule fires on CHANGELOG.md (long-line prose,
p95 913 chars) — a true giant-line shape that is not minified
anything. The message's "the minified signature" wording
overclaims the diagnosis. Fix: name the shape, not the cause —
"giant-line shape (minified code, compact data, or long-line
prose)". Detection logic unchanged.

### G3 [VERIFIED] Bogus profile mode fails as a config error
Probe: a profile mode of "bogus" makes lint exit 2 with
"lint: unknown mode for x.py: bogus" (resolve_modes ValueError
caught by the CLI) — the same error an export would produce,
not a lint-only divergence. Pin it with a test in Improve #2.

### G4 [VERIFIED] Real-tree behaviour (GhostBus + this repo)
GhostBus: lint completes, no L005 (the v0.4-flagged test keys
were replaced with placeholders earlier today — an independent
cross-check that fix holds), L003 surfaces the graph's known
config-wired "unreachable" candidates (hosted server, Netlify
function — the documented review-don't-delete class), L006
fires on the changelog's long lines (see G2). Self-lint after
the F1 fix: identical 4 findings (F1 changed a message string
only; counts unchanged).

### G5 [REVIEWED, SOUND] F1 fix edges
With <2 included copies the exact loop now skips early — same
result as before (the loop body never ran). Near-pair logic is
untouched. A file can in theory earn two L004 findings (exact
copy of one file, near-second of another); both messages are
true and the union totals count it once. Kept.

### G6 [REVIEWED, NO FINDINGS] Watch/dashboard interplay
watch's profile augmentation uses dataclasses.replace, which
carries the new lint field through untouched; the dashboard
_State computes lint once from the same cached scan/graph/
dups/secrets it already held, so /api/lint adds no second scan.

## Improve #2 (fixes applied)
- G1: L003/L005/L007 messages now carry their estimated token
  count; _print_lint no longer appends a duplicate "(est. ...)"
  suffix. Test pins the L003 message count.
- G2: L006 message reworded to name the giant-line shape with
  its three common causes; the action line matches.
- G3: bogus-profile-mode CLI exit 2 pinned by a test.

Final state after Improve #2: 334 tests passed (293 baseline +
41 new), `ghostslice secrets .` exits 0, version 0.11.0,
self-lint 4 warn findings (all justified in Audit #1), GhostBus
lint clean of errors. Committed locally; push/release is the
parent's step.
