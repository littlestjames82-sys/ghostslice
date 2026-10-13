# G16 Audit — Fuzz + encoding robustness (v0.21.0)

Goal: NO unhandled traceback from any command on ANY input bytes.
Malformed input degrades to a clear error (typed error -> CLI exit
code) or a documented fallback, always. Plus distinct encoding
correctness: BOM'd UTF-16/32, Latin-1, UTF-8 BOM, CR/CRLF/CR-only
line endings handled properly instead of approximately. Baseline:
v0.20.0, 614 tests passed.

## Build summary

- New `textio.py`: the one shared decode. BOM sniff (UTF-32 before
  UTF-16 — the LE BOMs share a prefix) -> matching codec, BOM
  stripped; else strict UTF-8; else Latin-1 (lossless byte->point
  mapping), labelled. Wired into every project-source read:
  scanner, exporter (3 sites), fit, graph, selection, callgraph,
  symslice (via callers), lint, duplicates, calibration,
  secrets_scan, watch, server, mcp_server, cli (explain/slice/
  symbols), entries, workspaces. Bundle internals (manifest,
  ledger, cache envelopes) keep their own strict readers: those
  files are machine-written, and a BOM there means tampering.
- Scanner: decode before the binary test (a wide BOM marks text);
  unknown-extension gate unchanged in effect (a "latin-1" verdict
  is exactly the old strict-decode failure); FileEntry gains
  `encoding`; line count switched to `len(splitlines())`; scan
  cache payload gains `encoding` (the gs-version key dimension
  orphans v0.20 entries anyway); unreadable root dir is now a
  PermissionError instead of a silent empty scan.
- Exporter: manifest entries gain `source_encoding` when not
  UTF-8; bundle `files/` written with `write_bytes` (exact bytes
  the manifest hashes).
- Guards: profile loading wraps JSON + field types into ValueError
  naming the file/field (CLI maps it to exit 2 for every command);
  `validate_bundle` shape-guards the manifest end-to-end and
  RETURNS failures; `bundlediff.load_manifest` raises ValueError
  with messages and its entry/total reads are normalized; the CLI
  validates model ids up front for the commands that resolve one
  and nets OSError into a clean exit 2; ast.parse sites broadened
  from `except SyntaxError` to `except Exception` (the
  selection.py precedent) so ValueError (NUL bytes) and
  RecursionError degrade to the fallbacks; configslice's JSON
  shape walk got a depth cap (100) plus a RecursionError degrade;
  dashboard POST and MCP message handling reject non-object JSON.
- Harness: `tests/fuzz_harness.py` — seeded (20261013),
  deterministic: 10 seed files x (raw + 9 mutation recipes) = 100
  corpus cases, 20 malformed profiles, 12 manifest mutations, 8
  ledger cases. `tests/test_v21_fuzz.py` drives library surfaces
  (slice_text x all modes, outlines, symbol slicing, secrets scan
  + redact, estimator) and the full CLI (30 commands on the
  all-corpus project, per-case single-file projects, check/diff on
  mutated bundles, path-robustness sweeps) under `main()` argv
  runs where any escaped exception fails the test.

## Audit #1 — fuzz campaign #1 + adversarial review

Pre-build probe (standalone, /tmp/probe16.py): 17 crashes in 3
classes, all confirmed before a line of the fix was written.

### F1 [HIGH] Malformed profiles crashed most commands
Invalid JSON -> raw JSONDecodeError; non-object top level and
type-wrong fields (ignore: 42, budget: "abc") -> ValueError /
TypeError escaping every command except lint (the only one that
caught ValueError). Fix (Improve #1): profile.py wraps read +
parse + per-field type validation into ValueError naming the
file and field; cli.py maps profile ValueError to exit 2 for ALL
commands. Profiles also tolerate a BOM (explicit intent) while
keeping non-UTF-8 bytes an error.

### F2 [HIGH] The validator raised on the bundles it exists to judge
`check` on a missing/malformed/list/empty manifest crashed with
FileNotFoundError / JSONDecodeError / TypeError / KeyError (5
probe cases). Fix: validate_bundle loads the manifest behind
shape guards and returns {ok: False, errors: [...]}; per-entry
accesses are .get()-based; wrapper validation receives a
sanitized manifest view; bundlediff normalizes what it indexes.
The G11 shape-guard pattern, now applied to the manifest itself.

### F3 [HIGH] Nonexistent project crashed 8 commands
scan/export/secrets/graph/explain/calibrate/report/task raised
FileNotFoundError tracebacks (lint/calls/symbols/init/check-
budget already returned 2 — the inconsistency was the tell). Fix:
CLI main() is now a thin wrapper over the implementation: FileNot
FoundError / PermissionError / NotADirectoryError / IsADirectory
Error / other OSError -> message + exit 2 (the print itself is
guarded for the broken-pipe case).

### F4 [MED] UTF-16/32 silently excluded; BOM/CR/Latin-1 wrong
Not crashes — wrong answers with exit 0, found by reading scan
output, not exceptions: UTF-16 and UTF-32 files scanned as 0
files (NUL binary test ran on raw bytes); a CR-only file
reported 1 line; a UTF-8 BOM cost a phantom token and broke
ast.parse into the fallback; Latin-1 content was mangled to
U+FFFD. Fix: the textio build above (decode first, binary test
on un-BOM'd bytes only, splitlines counting). Pinned by twin
tests: every encoding variant of one source yields identical
tokens/lines, ships its content in the bundle, and carries the
right manifest label.

### F5 [MED] RecursionError escaped the Python/JSON paths
ast.parse sites caught SyntaxError only; a 3,000-deep parenthesized
expression raises RecursionError (and NUL bytes raise ValueError)
straight through slice_text, graph, and callgraph. JSON structure
mode caught the loads but not the shape walk. Fix: parse sites
broadened to `except Exception` (degrade = the existing line
fallback / full text), _json_shape depth-capped at 100 with a
RecursionError degrade to full. Pinned in SizeGuardTests.

### F6 [MED] Bundle files failed their own sha256 when slices keep CRs
Found BY the harness (CliProjectSweep on EOL-mutated files), not
the probe: files were written with write_text and re-read with
read_text, whose universal-newline mode translates \r\n/\r -> \n —
so the text being hashed at validation was not the text written.
Any full-mode CRLF doc/config bundle was affected, not just fuzz
mutants. Fix: files/ written as exact bytes (write_bytes) and
validation reads bytes + decodes. Companion find in the same
sweep: the XML validator compared parser output (which per XML
1.0 section 2.11 has CR/CRLF normalized to LF — spec-mandated,
inherent to the format) against the raw slice; comparison now
goes through _xml_roundtrip_text (safe-chars + LF normalization),
the second documented lossy step for context.xml after U+FFFD.

### F7 [LOW] Non-object JSON crashed the network surfaces
Dashboard POST body [1,2] -> AttributeError on body.get; MCP
lines carrying a JSON array/scalar, a non-string method, or
non-dict params crashed handle_message/run_stdio. Fix: isinstance
guards -> 400 / skip / JSON-RPC error results. Pinned in
McpRobustnessTests.

### F8 [LOW] My own test design, twice
The G11 invalid-UTF-8 test pinned U+FFFD output — the exact
contract this goal replaces; updated to the Latin-1 expectation
with the round-trip + validation assertions intact and a new
source_encoding assertion (the ONLY pre-existing test changed).
The cache-corruption test originally built bundles inside the
scanned root, so build #2 scanned build #1's bundle (totals
114 -> 804 with a clean cache too); rebuilt to build outside the
root and compare against a use_cache=False ground truth.

## Audit #2 — campaign #2: new seed, new shapes, new surfaces

Re-ran the full campaign (0 failures) plus: seed 777 corpus
through the library surfaces; empty/1-byte/BOM-only files in 10
extensions; a 300-deep directory tree; unicode/space filenames;
duplicate JSON keys in a profile; a manifest with duplicated file
entries (check correctly returns 1); notebook cells of wrong
shapes. New finds:

### F9 [HIGH] A FIFO in the tree hung the scanner forever
A named pipe with a .py suffix blocked read_bytes indefinitely
(confirmed by timeout kill, rc=124): the purest hang in the
campaign, on input that occurs in real trees. Fix (Improve #2):
the scanner stats candidates and only reads regular files
(FIFOs/sockets/devices skipped, like binaries). Pinned with an
mkfifo regression test that asserts completion inside the case
budget. (Manifest readers in entries.py — a FIFO literally named
package.json — remain a documented theoretical hole; entry
analysis works from scanner output, which is now regular-only.)

### F10 [MED] Unknown --model trace-backed 4 commands
`scan --model nope` raised KeyError from pricing.get_model;
task/export/report resolved models at similar unguarded depths,
and a bad profile model crashed the same way (history and init
already guarded theirs — same inconsistency class as F3). Fix:
the CLI validates --model/profile model ids up front for exactly
the commands that resolve one (scan/export/task/report/history/
serve), exit 2 with the valid-ids pointer. Pinned per command.

### F11 [LOW] Sweep residue, verified clean
Symlink loop in a tree: ELOOP read error -> file skipped, no
hang; a symlink to a regular file is followed (documented
behaviour, matches pre-v0.21). A .ghostslice.json that is a
directory is ignored (no profile), by load_profile's is_file
gate. chmod-000 subdirectories are skipped by os.walk; a
chmod-000 root now errors cleanly via the new PermissionError
(the container runs as root, so the strict test self-skips —
the code path is the scanner raise + F3's wrapper).

## Performance / limits (measured, this sandbox)

- Estimator + brace matcher scale linearly on adversarial input:
  unbalanced-brace JS at 20k/80k repetitions costs a ~4x time
  ratio for 4x input (test-pinned bound: <8x); a 10 MB single
  line slices in ~0.1 s; a 17 MB ordinary JS file slices in
  ~6-14 s by mode (~0.4-0.8 s/MB — the documented rate; there is
  no size cap, by design). A 102k-line Python file exports in
  ~4 s. Deep-nesting degrades are effectively instant (fallback
  paths). No quadratic or ReDoS behaviour found anywhere probed.

## Limitations (documented in README)

- Wide encodings are BOM-detected only; BOM-less UTF-16 reads as
  binary, as before.
- Latin-1 is the fallback for ALL non-UTF-8 bytes: a file in a
  non-Latin-1 legacy encoding (e.g. Shift-JIS without BOM) decodes
  as mojibake rather than being skipped — labelled "latin-1" in
  scan output so the misread is visible, and unknown-extension
  files still require valid UTF-8-family bytes to be admitted.
- Files are read fully into memory; very large files are slow
  (linear), not capped.
- Genuine I/O races (a file deleted between scan and slice) end
  at the CLI's OSError net: exit 2 with the OS message.

Final state: 642 tests passed (614 baseline + 28 new in
tests/test_v21_fuzz.py; 1 skip: the chmod test self-skips as
root), 1 pre-existing test updated (the G11 U+FFFD pin — see
F8), `ghostslice secrets .` exits 0, version 0.21.0.
