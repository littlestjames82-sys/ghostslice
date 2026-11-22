# GhostMCP Doctor - Agent B Report (tests / README / examples)

Date: Oct 14, 2026. Scope owned and edited by Agent B only: `tests/**`,
`README.md`, `examples/**`, this file. `src/**`, `pyproject.toml`, and
`PLAN.md` (Agent A's) were read read-only after they landed, never edited.
No network, no push, no publish, no announcements, no spend.

## Result: PASS, 34/34 tests, run twice

```
$ python3 -m pytest tests -q     (from ~/workspace/ghostmcpdoctor)
34 passed in 12.25s
34 passed in 13.62s   (second run)
```

Breakdown: fixtures sanity 10, scan findings 9, redaction 5,
read-only + edges 9, report re-render 1.

## The mandated test

`tests/test_redaction.py::test_fake_secret_value_never_appears_in_report_output`
plants two unique FAKE canaries as env values in
`tests/fixtures/messy/mcp.json`
(`FAKE-SECRET-CANARY-DOCTOR-7f3a9c-never-print`,
`FAKE-TOKEN-CANARY-DOCTOR-51bd02-never-print`), scans it, and asserts
neither string appears in stdout, stderr, the JSON report, or the
Markdown report. Companion tests repeat the check in `--json` mode,
in directory-scan mode, for the shipped example config, and on a
`report` re-render round trip. A positive control proves redaction is
not silence: the report names the server and its env key names as
present (the core renders inventory env as `{key: "present"}`).

## Contract alignment (harness first, then PLAN, then landed core)

Tests were started against the task scope before Agent A's PLAN/core
existed, with all adaptation isolated in `tests/conftest.py`
(entrypoint + subcommand discovery, scan attempts, report collection).
When PLAN.md landed mid-session it confirmed: `scan` / `report`
commands, `--config`, `--home` / `--project`, `--out-dir`, `--json`,
`--no-report`, exit codes 0/1/2, reports `mcpdoctor-report.json` +
`MCPDOCTOR.md`, finding codes DUPLICATE / MISSING-COMMAND /
MISSING-FILE / EMPTY-SERVER / DISABLED / BROAD-FILESYSTEM /
BROAD-ENV / SHELL-WRAPPER / PARSE-ERROR. The harness needed no
structural change; four fixture/test corrections came from reading
the landed `scanner.py` / `checks.py`:

1. DUPLICATE is name-based (PLAN verification bar), not
   command+args-based. The messy pair `filesystem-main` /
   `filesystem-copy` (same command+args, different names) is now
   asserted as inventoried + broad-flagged, not as a duplicate. Real
   duplicate coverage: `duplicates_across_files/` (same name in
   `mcp.json` and `.cursor/mcp.json` - the layout directory discovery
   actually finds) and `duplicate_scopes/` (same name at top level
   and under `projects.<path>.mcpServers`, the in-file form).
2. Path-like args are existence-checked (MISSING-FILE), so the clean
   fixture dropped its `--root /tmp/example-project` arg (that path
   does not exist, and flagging it would be correct behaviour). The
   clean fixture is now a single `python3 -m example_docs_server`
   server and scans exit 0 with an empty findings list, judged on
   the structured report.
3. A dedicated stale-script server (`./definitely_missing_script_9f3k.py`)
   covers MISSING-FILE per the PLAN verification bar.
4. Two text-window assertions were replaced with structured checks
   against the real `mcpdoctor-report.json`, because the core's own
   summary legitimately contains the words "duplicates: 0" and a
   MISSING-COMMAND explanatory note, which poison naive windows.
   One harness bug of mine was also fixed along the way: the JSON
   test initially parsed the concatenated combined output instead of
   stdout / the report file.

No core defects were found. One core behaviour worth knowing:
`reports.py` sets exit 1 when *any* finding exists, including an
info-only DISABLED finding, where PLAN.md words exit 0 as "no
findings above info". No test here plants a disabled-only config, so
nothing in this suite turns on it; flagged for the parent / Agent A
to adjudicate against the plan wording.

## Fixtures built

- `clean/` - one narrow enabled python3 server, no findings due.
- `messy/` - filesystem pair granted `/` (BROAD-FILESYSTEM x2), a
  nonexistent command (MISSING-COMMAND), a missing script arg
  (MISSING-FILE), a bash server (SHELL-WRAPPER), and the canary
  secret server (no finding, keys present only).
- `duplicates_across_files/`, `duplicate_scopes/` - see above.
- `invalid/broken.json` - unparseable JSON (PARSE-ERROR, reported,
  never passed, no traceback).
- `empty/` - `{"mcpServers": {}}` (scans, no crash).
- `vscode/` - VS Code `servers` container shape.

Read-only is proved, not trusted: config bytes, file lists, and
mtimes are hashed/recorded before and after text, JSON, and
directory scans and must be identical.

## README and examples

- `README.md` - the secret rule up front, install, quickstart, both
  commands with all flags, the findings table with severities and
  the stale label, exit codes, report contents, and the honest
  limits (PATH evidence not proof, plain JSON only in v0.1, no
  trust verdicts). Pricing stated as not decided, per PLAN.
- `examples/` - five sample configs (Claude Code, Cursor,
  Antigravity-shaped, VS Code, messy), FAKE env values only, plus
  `README.md` (index) and `WALKTHROUGH.md`. Every walkthrough
  command was run verbatim against the landed core on Oct 14, 2026:
  clean sample 2 servers / 0 findings / exit 0; Claude Code + Cursor
  samples together 1 DUPLICATE (`project-docs`) / exit 1; messy
  sample 3 findings (BROAD-FILESYSTEM x2, MISSING-COMMAND) / exit 1;
  `grep -rn "FAKE-EXAMPLE"` over all produced reports found no fake
  value anywhere; the `report` re-render reproduced both report
  files and inherited exit 1.

## Gates honoured

Local only. No push, no publish, no announcements, no spend. Tests
run the core as a local subprocess against copies of the fixtures in
pytest tmp dirs, so checked-in fixtures are never written by a run.
Files outside the Agent B ownership list were not edited.
