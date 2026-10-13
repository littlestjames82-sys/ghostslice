# G11 Audit — XML + JSON bundle formats (v0.16.0)

Goal: `anthropic-xml` and `json` export presets writing context.xml /
context.json from the same in-memory slice results as PROMPT.md, with
validator support and honest wrapper-overhead reporting.
Baseline 462 tests; build brought the suite to 485 (23 new in
tests/test_v16_formats.py).

## Audit #1 (after build)

### F1 [MEDIUM] Validator crashes on a wrong-shaped context.json
_validate_wrapper_artifacts assumes payload["files"] /
payload["excluded"] are lists of objects. A hand-broken (or
foreign-tool-written) context.json that is valid JSON with the wrong
shapes — files: [42, {...}], excluded: ["oops"], files as an object —
makes validate_bundle raise AttributeError ('int' object has no
attribute 'get') instead of returning ok: False with errors.
Reproduced with a probe before writing this finding. A validator's
whole job is to judge broken input; it must never crash on the
artifact it exists to check. (The manifest side is pre-existing
behaviour — validate_bundle has always assumed manifest shape; the
artifact payload is a NEW surface this goal added, so the bar is
set here.) Fix: shape-guard both lists (non-list -> one clear error;
non-object entries -> one error each, skipped), with regression
tests.

### Categories audited with no findings
- XML escaping: content is escaped by ElementTree only — no
  hand-rolled escaping, no CDATA anywhere (a test asserts the
  literal "<![CDATA[" never appears). Adversarial fixture carries
  ]]>, <tag attr="a&b">, &amp;, bare & <>, and DEL (\x7f, legal in
  XML 1.0): byte-for-byte round-trip via minidom parse against the
  bundle's own files/ bytes.
- Attribute injection: a file named we"ird.py round-trips in both
  formats (ET escapes attribute values; probe verified), CRLF and
  whitespace-only slices validate, an empty project produces valid
  <documents/> and an empty-files context.json, both validating.
- Illegal XML characters: \x01 / \x0b slices still yield parseable
  context.xml (U+FFFD substitution, files/ keeps canonical bytes,
  validation passes — validator compares XML content against
  _xml_safe_text(disk bytes), so the lossy step is checked, not
  assumed). Pinned by test.
- Lone surrogates cannot reach json.dumps: sources are read with
  errors="replace" (which yields U+FFFD, never surrogates), and in
  the same build loop files/ are written as UTF-8 BEFORE any
  artifact is rendered — a hypothetical surrogate would already
  fail every preset identically. The reachable invalid-bytes path
  is pinned by the bad.txt test (U+FFFD round-trip).
- No divergence: both renderers consume the `included` /
  `excluded_records` lists built in build_bundle's single slicing
  loop; the included set is exactly the files/ + PROMPT.md set
  (mode != exclude and non-empty slice), the excluded set is its
  complement over the manifest, and a test asserts the union equals
  the manifest file set with empty intersection for both formats.
- Totals semantics: manifest totals are still sums over manifest
  files only (pinned by the wrapper-overhead test); the wrapper is
  measured on the artifact text AS WRITTEN (escaped form — what a
  consumer model would actually ingest) and reported separately in
  manifest["wrapper_artifacts"] + the CLI line.
- Wrapper estimator: estimate_tokens(text) with no language is the
  raw split (factor 1.0); language_for("context.xml") resolves to
  "text" whose family factor is also 1.0 today, so the wrapper
  figure is the same either way — no hidden estimator mixing.
- Determinism: documents/files follow manifest order, index is
  1-based sequential (pinned), json.dumps preserves insertion
  order, ET attribute order follows the schema dict.
- Composition: task --preset anthropic-xml and export --fit with
  the json preset both build + validate (tests); --fit runs before
  the slicing loop, so artifacts reflect the fitted modes.
- MCP: preset enum follows PRESETS (v0.5 wiring), so both new
  presets are exposed without an mcp_server change; a tools/call
  export_bundle with preset json writes context.json (test).
- Old bundles: no context.xml/json -> validate_bundle behaves as
  before; the only return-shape change is the additive
  "artifacts_checked" key (bundlediff and watch consume "ok" /
  "errors" only).

## Improve #1 (fixes applied, suite 485 -> 488)
- F1: _validate_wrapper_artifacts now shape-guards the JSON lists
  via _json_records: a non-list "files"/"excluded" produces one
  clear error and is treated as empty; non-object entries produce
  one error each and are skipped. Three regression tests (non-object
  file entry, non-object excluded entry, files-as-object) assert
  ok is False with artifact errors and NO exception.

## Audit #2 (of the build + Improve #1 fix)

Probes run against the fixed validator; no new defects found.

- Wrong-TYPED values inside otherwise-object entries
  ({"path": 42, "sha256": null, "content": 7}): two clean errors,
  no exception — the shape guard plus the existing comparisons
  cover the value layer without more code.
- Duplicate <document> elements for one path in context.xml: the
  duplicate check fires ("duplicate entry for ..."), validation
  fails. A document whose file was deleted from files/ fires
  "content for ... but no sliced file in bundle" plus the
  excluded-list mismatch — two true statements about one tamper,
  accepted.
- Presence semantics confirmed deliberate: a stray (even broken)
  context.xml copied into a plain claude-code bundle IS validated
  and fails that bundle. That is the spec'd "validate when present"
  behaviour — ignoring an artifact because the manifest preset
  names another would let a corrupted artifact ride along
  unchecked. Recorded as a choice, not a bug.
- XML side needs no twin of _json_records: ElementTree gives a
  typed tree (elements/attributes/text), and missing <source> /
  <document_content> already degrade to "" and fail the
  unknown-file / content comparisons by name.
- Full suite after the fix: 488 passed; `ghostslice secrets .`
  exit 0; the original F1 crash probe now returns ok: False with
  four precise errors.

## Improve #2 (one real fix, found by the finishing smoke)

The Audit #2 probes found no defect, but the end-to-end smoke
(exporting this repo with both presets) exposed a presentation
bug in what Audit #1 had waved through: the CLI printed
"context.xml adds ~111,671 estimated tokens of format overhead on
top of the sliced totals" — the artifact's ENTIRE estimate
labelled as overhead. The artifact CONTAINS the slices; pasting
it replaces them, it does not add its whole size on top. On a
small bundle the two readings differ little; on a real one the
line overstates the wrapper cost by roughly the whole context.

- wrapper_artifacts gains overhead_estimated_tokens =
  max(0, artifact estimate - sliced total), the markup cost
  beyond the slices; the artifact's own estimated_tokens stays
  (it is the honest "what pasting this file costs" figure).
- The CLI line now prints both numbers ("context.xml is ~N
  estimated tokens in total ..., of which ~M is format overhead
  beyond the sliced totals"); README, CHANGELOG, and the
  exporter docstring were aligned, and two tests pin the
  definition (overhead == max(0, est - sliced total), strictly
  less than the artifact total; CLI line wording).
- The rest of the round was the finishing consistency pass:
  README preset list, layout line, and the "XML and JSON
  bundles" section re-read against the shipped schema field by
  field; the preset-consistency test guards PRESETS == profile
  loader == CLI choices == README list from here on.

Final state: 488 tests passed (462 baseline + 26 new), version
0.16.0, `ghostslice secrets .` exits 0, live smoke of both
presets on this repo validates. Committed locally; push/release
is the parent's step.
