# GhostMCP Doctor v0.1 - Polish Round

Oct 14, 2026, at Ryan's "Polishing" direction after Wave 3 parent
verification (34 tests passing). Sole folder owner for this round.
House loop: audit first, then two distinct improvement passes,
demonstrate-then-fix, a regression test for every fix. No version
bump, no release, no push, no publish, no announcements, no spend.
Stdlib only, local only, scanner still read-only.

Final result: **44 passed** (`python3 -m pytest tests -q`, run at the
end of the round), up from the 34-test baseline, which was re-run
green before any change was made.

## Audit findings (all demonstrated before fixing)

Probed with throwaway configs in /tmp against the shipped core:

1. **Info-only exit code (the adjudicated quirk).** A config whose
   only finding was an info-level `DISABLED` exited **1**.
   `reports.py` set exit 1 when *any* finding existed, while PLAN.md
   defines exit 0 as "scanned, no findings above info". Code
   contradicted the plan.
2. **Non-object server container scanned as clean.** `mcpServers`
   given as a list or a string produced **exit 0 with no findings**:
   `_collect_servers` silently skipped a non-dict container. PLAN.md
   names exactly this a `PARSE-ERROR` ("a discovered config that is
   not valid JSON **or whose server container is not an object**").
   A false clean on a malformed config is worse than a wrong exit
   code: it tells the user a broken wiring file is fine.
3. **BOM = parse error.** A valid config starting with a UTF-8 BOM
   (common in editor-written files) came back `PARSE-ERROR` with 0
   servers, because the file was decoded as plain `utf-8`.
4. **Duplicate scope detail said nothing.** For the in-file scope
   duplicate, the finding detail was "also defined in `<same file>`" -
   true and useless. The record carries a `scope` field; the finding
   dropped it, so the user could not tell *where* in the file the
   other definition lives.
5. **URL field kept the port.** Userinfo, query and fragment were
   stripped correctly (verified with a canary planted in all three),
   but the stored value was `api.example.com:8443`, not the host
   only that PLAN.md and the README promise.
6. **Stale stored exit codes on re-render.** The `report` command
   returned the stored `exit_code` verbatim, so any report written
   before a fix to the rule would keep re-rendering (and exiting)
   with the old wrong code forever.

Checked and found sound (no change): cross-file and both-keys
(`mcpServers` + `servers`) duplicate detection; parse-error in one
file not blocking other files; secret canaries absent from every
surface; read-only guarantee; bare-name `MISSING-COMMAND` PATH
behaviour (already documented as evidence, not proof).

## Pass 1 - make the code match the plan (severity / parse shape / recovery)

- `reports.py`: new `exit_code_for(findings, configs_scanned,
  fallback=None)` is the single implementation of the PLAN rule:
  2 when nothing was scanned, 1 when any finding is above info,
  else 0. `build_report` uses it. An info-only report now exits 0.
- `cli.py`: `report` recomputes the exit code from the stored
  findings via the same helper (keeping the stored value only as a
  fallback when the report lists no configs) and writes the
  corrected code into the re-rendered JSON. Old reports self-heal
  on re-render instead of inheriting finding 6.
- `scanner.py`: `_collect_servers` now returns `(servers,
  bad_container)`. A present-but-non-object container sets the
  config's status to `parse-error` (so checks emit `PARSE-ERROR`),
  while servers from well-formed containers in the same file are
  still collected - recovery, not abort.
- `scanner.py`: configs are decoded as `utf-8-sig`, so a BOM is
  tolerated and plain UTF-8 reads unchanged.

Demonstrated after Pass 1 with the audit probes: disabled-only ->
rc 0 / exit_code 0 with the `DISABLED` info finding intact; list and
string containers -> `PARSE-ERROR`, rc 1; BOM config -> rc 0, 1
server, no findings.

**On the required fix, code-vs-plan:** the code was changed to match
the plan, not the other way round. The plan's wording is the safer
contract: `DISABLED` is explicitly info and "stale evidence" - a
note for a human, not a failure - and the clean-config bar in the
same plan already treats "nothing above info" as the pass
condition. Making info findings fail the scan would train users to
ignore exit 1, which is the signal that matters for warnings and
errors. The plan text stands unchanged.

## Pass 2 - finding quality and redaction exactness

- `checks.py`: `DUPLICATE` details now name scopes. When either
  definition sits in a nested scope, the detail says so
  ("also defined in `<path>` (scope: projects.<dir>)",
  "this definition is in scope: ..." / "at top level").
  Cross-file top-level duplicates produce byte-identical details to
  before, so nothing already published about that case moved.
- `scanner.py`: `_safe_url_host` now returns `urlparse(...).hostname`
  - host only. Userinfo, port, path, query and fragment are all
  dropped from the one URL field a report keeps (finding 5).
  Scheme-less URLs still yield "" (safe, unchanged).
- Regression fixtures: `tests/fixtures/disabled_only/` (one disabled
  `python3` server) and `tests/fixtures/bad_container/`
  (`mcpServers` as a list).
- New suite `tests/test_polish_regressions.py`, 10 tests, one per
  fix: disabled-only scan exits 0 (fixture + structured report);
  info + error together still exit 1; disabled-only re-render exits
  0; a hand-built stale report with stored exit 1 and info-only
  findings re-renders to exit 0; non-object container is a
  `PARSE-ERROR` with status `parse-error`; a bad container beside a
  good `servers` container still inventories the good server; a
  broken file scanned alongside a clean file yields both the
  `PARSE-ERROR` and the clean server; a BOM config parses; the
  duplicate-scope detail contains the scope; a URL carrying a canary
  in userinfo, query and fragment plus a port stores exactly
  `api.example.com` and leaks nothing anywhere.
- README accuracy: the exit-code table now states the info-only rule
  and the re-render recompute behaviour (it previously said the
  re-render "inherits" the stored code); the limits section notes
  BOM tolerance and the non-object-container `PARSE-ERROR` with
  continued scanning; the Tests section names the two new fixtures.
  `examples/WALKTHROUGH.md` re-render wording updated to match
  (outcome for its messy example is unchanged: still 1).

## What was left alone, on purpose

- **PLAN.md** - unchanged. The plan was right on every audited
  point; the code was what drifted.
- **Severity assignments** - `DISABLED` stays info/stale; no finding
  was re-graded to make the exit rule easier.
- **Case sensitivity of server names** - `Docs` vs `docs` are
  different servers to every client Doctor reads; not flagged, and
  adding case-folding would invent duplicates the clients do not see.
- **`projects` degradation** - a non-dict `projects` value or
  non-dict project entry is still skipped silently: it is not a
  server container, and flagging it would go beyond the plan.
- **HISTORICAL records** - `IMPLEMENTATION_A.md` / `REPORT_B.md`
  still describe the original build (including a since-fixed
  conftest note); they are build records, not user docs, and were
  not rewritten. This file is the polish record.
- **Version** - still 0.1.0 in `pyproject.toml`; no tag, no release.

## Gates held

Stdlib only (no new imports beyond the standard library), local
only, no network, read-only (the suite's byte + mtime identity tests
still pass), secret rule unchanged and still structural - env values
are discarded at parse time and no output surface gained any new
field that could carry one. Files outside
`~/workspace/ghostmcpdoctor/` were not touched (audit probes lived
in /tmp and were removed).
