# GhostExposure v0.1 - Implementation A (core builder)

Built Oct 14, 2026 from PLAN.md. Python stdlib only, no network.
Evidence only throughout: no verdicts, grades, or scores in any output or
copy, no scanning beyond the patterns stated in the surface pack and the
secret-shape list, and no framing in any file that goes beyond facts and
manifests.

## Files owned and written by Agent A
- `pyproject.toml` - package ghostexposure 0.1.0, script `ghostexposure`.
  Note: it references README.md (owned by Agent B); until that file lands,
  run via PYTHONPATH instead of pip install.
- `src/ghostexposure/__init__.py` - version 0.1.0 plus the two canonical
  statements used everywhere: COVERAGE_STATEMENT and CANNOT_PROVE_STATEMENT.
- `src/ghostexposure/surface.py` - surface pack loading/validation
  (required fields, kind must be "surface", pattern kinds glob/symbol/
  import/data, each pattern needs id/kind/pattern/reason).
- `src/ghostexposure/inventory.py` - full-tree inventory: sorted walk,
  .gitignore honoured (basic patterns), default ignore dirs, per-file
  sha256/size/text flag, inventory_hash over path+sha256, token estimator
  (chars/4, labelled estimate).
- `src/ghostexposure/secrets.py` - secret-shaped literal detection
  (AWS key, GitHub token, sk- style key, bearer, generic key/secret/token/
  password assignments, private-key header, long hex assignment).
  Findings carry line + type only; values are never recorded.
- `src/ghostexposure/partition.py` - partition engine. Every inventory
  file gets exactly one decision: surface / context / out / conflict,
  with reason codes (glob, symbol, import, data, graph-neighbour,
  user-pinned-in, user-pinned-out) and the matched pattern ids/reasons.
  Graph context = distance-1 callers of the surface: files that import
  a surface file (Python ast imports incl. from-import submodule
  resolution, regex fallback for other languages). A helper merely
  imported BY a surface file is not pulled in by this rule. This
  direction was confirmed against Agent B's fixtures (app/main.py is
  the graph neighbour, util/format.py stays out).
  Pins come from the project `.ghostslice.json` `exposure` section;
  both `pinned_in/pinned_out` and `pin_in/pin_out` spellings are
  accepted. Pack loading also normalises a `dated` field to `date` and
  a string `coverage_limits` to a one-item list.
  Conflict rule: surface match + user pin-out = conflict, never resolved
  silently (see export behaviour below).
- `src/ghostexposure/exporter.py` - export and verify.
  Export layout: `files/<rel>`, `manifest.json` (Slice-style: path, mode,
  decision, reasons, original/exported estimated tokens, sha256),
  `exposure.json` (surface pack snapshot incl. every pattern, inventory
  hash, full partition, counts, redactions, flags, both limit
  statements), `EXPOSURE.md`, `PROMPT.md`.
  Surface files are exported full; Python context files are exported in
  signatures mode (own stdlib ast implementation); non-Python context
  falls back to full and the manifest mode says so.
  Secret-shaped literals in exported copies are redacted by default
  (`***REDACTED***`) and recorded (path + line + type) in exposure.json.
  `--allow-unredacted` leaves them as-is and records that choice.
  Unresolved conflicts stop export with exit 2; `--exclude-conflicts`
  leaves them out and records `conflicts_excluded_by_explicit_flag`.
  Source tree is never modified (verified in smoke test).
  Verify: re-checks manifest hashes, files-on-disk set equals the
  manifest set (extra and missing files both named), partition lists
  each inventory file exactly once, inventory hash recomputes from the
  partition, and EXPOSURE.md contains both required statements.
- `src/ghostexposure/cli.py` / `__main__.py` - commands: `scan`
  (text or --json, exit 1 when conflicts exist), `export`, `verify`
  (exit 0/1, always prints both limit statements), `packs` (shows the
  loaded pack and every pattern). `--version` works.
- `surfaces/starter.json` - first surface pack: id
  `auth-payments-secrets-data` v1.0.0 dated 2026-10-14, 25 patterns
  (glob/import/symbol/data for auth, login, payments, billing, checkout,
  secrets, tokens, env files, Stripe/PayPal/jwt/bcrypt/passlib/environ,
  password/token symbols, email/card/ssn/dob/api_key data shapes),
  each with a plain-words reason, plus 4 coverage_limits entries.

## Smoke test (run by Agent A, /tmp fixtures, Oct 14, 2026)
Fixture: 6-file Python project (main, auth/login with bcrypt + a planted
sk- style key literal, billing/charge with Stripe import, utils/helpers
imported by login, README, notes.txt).

- scan: login + charge correctly surface with glob/import/symbol/data
  reasons; README + notes = out. Counts surface 3 (main also matched
  the authenticate symbol pattern), context 1, out 2, conflict 0.
  Coverage statement + all 4 pack limits printed. Context was
  demonstrated on an added caller fixture (app/runner.py imports the
  billing module, carries no pattern of its own, and lands as
  graph-neighbour context in `signatures` mode in manifest.json);
  a helper imported by a surface file (utils/helpers.py) stays out,
  matching the caller-direction rule above.
- export: bundle written; 3 surface + 1 context in bundle.
- Key test: planted literal occurs 0 times anywhere in the bundle;
  exposure.json records 1 redaction (app/auth/login.py line 3,
  openai_style_key), no value recorded. Source file still contains the
  literal (source untouched).
- verify on clean bundle: exit 0, prints the cannot-prove-other-channels
  statement and the coverage statement.
- Tamper (add files/extra.py): verify exit 1, names extra.py as present
  but not recorded. Tamper (remove charge.py): verify exit 1, names it
  as recorded but missing. Restored bundle verifies exit 0 again.
- Statements: EXPOSURE.md contains the coverage-limits statement and
  the cannot-prove statement (grep counts 2 and 1).
- Conflict fixture (.ghostslice.json exposure.pinned_out = app/auth/*):
  scan lists login.py as `conflict` (exit path noted), export refused
  with exit 2 naming the file, export with `--exclude-conflicts`
  succeeds and exposure.json records
  conflicts_excluded_by_explicit_flag: true; that bundle verifies exit 0.
- compileall on the package: OK. `--version`: ghostexposure 0.1.0.
- Copy check: grep over src/surfaces/pyproject for verdict/assurance
  vocabulary (score, grade, certified, compliant, safe, secure,
  vulnerab*) returns no user-facing claims. The only match found during
  the build (a negative statement in the package docstring) was reworded.

## Known limits (per the plan's honesty rules)
- .gitignore support is basic fnmatch (no negation, no per-directory
  .gitignore files beyond the root one).
- Graph neighbours are import-based only; dynamic imports and call-only
  relationships in non-Python files can be missed, and the coverage
  limits say pattern outcomes are all that is recorded.
- Token numbers are chars/4 estimates, labelled as estimates in the
  manifest and EXPOSURE.md.
- Signatures mode is Python-only in v0.1; other languages' context
  files export full with the true mode recorded.
- No GhostSlice code is imported: bundle/manifest conventions match
  Slice's documented shape, but `ghostslice check` compatibility has
  not been cross-run by Agent A (that check belongs to parent
  verification).
- Agent B's test suite (tests/**, landed in parallel) was run against
  this core at the end of the build: 25 passed, 0 failed
  (PYTHONPATH=src python3 -m pytest tests -q). Three interface
  alignments were made in Agent A's files to get there, with no test
  files touched: pack field normalisation (`dated`, string
  coverage_limits, optional kind), pin spelling aliases, exposure.json
  alias keys (`files` for the partition list, `surface` summary,
  `inventory_sha256`), graph-context direction (callers only), and
  from-import submodule resolution.

## Addendum, Oct 14, 2026 (seam-fix round)

The `secrets.py` bullet above describes the shape list as built. It is
superseded by SEAM_FIX_REPORT.md: the ecosystem pass found the
aws_access_key pattern was AKIA-only while GhostSlice's canonical guard
covers AKIA and ASIA, and the fix round aligned the whole shape list
against Slice's canonical list (per-shape parity/divergence record in
the report). This file stays as the dated build record.
