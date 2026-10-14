# G20 Audit — v1.0.0: doctor, completions, CLI polish, docs, readiness

Goal: `ghostslice doctor` health check, parser-generated shell
completions, the mockup scan/fit layout polish (top-N heat bars +
% of total + summary box; fit report as a table), the docs
completion pass (feature map, stranger quickstart,
troubleshooting), the version bump to 1.0.0, and a full
release-readiness audit. Baseline 760 tests; build brought the
suite to 784 (24 new in tests/test_v25_release.py), with ZERO
existing tests modified — the layout changes touched no pinned
expectation (existing scan/fit assertions were section- and
key-level, verified by the full green run; the deliberate new
layout is pinned by the new tests instead).

Design summary: doctor.py runs ten read-only checks (python,
version, estimator, prices, profile, cache, ledger, plugins,
git, workspace), each ok/warn/fail with a one-line remedy for
warn/fail; the CLI dispatches doctor BEFORE the generic profile
load and plugin activation so a broken profile or failing
plugin is reported, not fatal, and a broken price table steps
aside for doctor (prices=None) because reporting it is doctor's
job. completions.py walks the live argparse parser (one source
of truth); the shipped scripts in examples/completions/ are
pinned byte-equal to fresh output. Scan polish is confined to
_print_scan/_print_fit; every JSON payload is untouched.

## Pre-build finding (found in baseline recon, fixed in build)

### F0 [HIGH] pyproject.toml version drifted two majors behind
`ghostslice.__version__` said 0.24.0; pyproject.toml still said
0.16.0 — so a `pip install .` produced a distribution whose
metadata disagreed with the tool it installed. Nothing in
0.17-0.24 noticed because every runtime surface reads
`__version__`. Fix (build): both now 1.0.0; doctor's version
check cross-checks the two in a source checkout (fail +
remedy), and a test pins the agreement permanently.

## Audit #1 — the readiness matrix

Environment: this sandbox, Python 3.12.3, fresh temp dirs.
GhostBus runs used a COPY in /tmp so exports could not write
ledger files into the real repo.

### Command matrix (exit codes; full run ~54s)
Every command run once per project; ALL exit 0.

ghostslice repo: scan 0, scan --json 0, scan --top 3 0,
graph 0, slice tree 0, export 0, export --fit 0, task 0,
symbols 0, calls 0, calls --dead 0, secrets 0, report 0,
watch --once 0, init --dry-run 0, lint 0 (7 warns, honest),
check-budget 0, ci 0, history 0, history --trend 0,
calibrate 0, cache stats 0, doctor 0 (9 ok, 1 warn),
doctor --json 0.
GhostBus copy: the same 24 commands, all 0; doctor 10 ok;
totals unchanged at 129,555 -> 45,770 estimated tokens.
Cross: explain (repo file) 0, explain (ghostbus file) 0,
check bundle 0, diff bundles 0, prices 0, completions
bash/zsh 0, --version 0 ("ghostslice 1.0.0"), --help 0.

### Stranger pass
- README Quickstart run verbatim from the repo root:
  scan 0, doctor 0, export --fit 60000 0, check 0,
  history --trend 0.
- Install: `python3 -m venv` + `pip install .` from a clean
  copy of the tree SUCCEEDED (setuptools build backend
  resolved in this sandbox): "Successfully installed
  ghostslice-1.0.0". The installed `ghostslice` binary then
  ran --version (1.0.0), doctor (10 ok), and scan against
  the GhostBus copy; dist metadata reports version 1.0.0,
  Requires-Python >=3.10. No PYTHONPATH substitution was
  needed; the fallback would have been documented here.
- MCP: initialize returns serverInfo {ghostslice, 1.0.0};
  tools/list returns all 6 tools (scan_project, slice_file,
  estimate_cost, lint_project, check_secrets, export_bundle).
- Dashboard: `serve` boots; GET / returns the page, /api/scan
  returns the scan payload, /api/slice returns a live slice
  of the new doctor.py.
- Dogfood CI, verbatim workflow command
  (`ci . --budget 180000 --json --out ...`): exit 0, payload
  exit_code 0; budget check at 150,024 of 180,000 (83%);
  secrets pass; lint warn only (see F4).

### Doctor adversarial probes (beyond the test fixtures)
- cwd prices.json with an empty models list: doctor prints
  [FAIL] Price table + remedy and exits 1 — the full report
  still prints (the CLI's early price-table exit steps aside
  for doctor by design).
- cwd prices.json with models but no as_of: [WARN] + remedy.
- Corrupt cwd prices.json: covered by test
  (test_doctor_survives_broken_prices).
- Doctor against a missing directory: exit 2, clean message.
- Doctor never writes: pinned by tree-snapshot test.

### Findings

#### F1 [LOW] README's unittest claim overpromises
The Tests section offers `python -m unittest discover` as an
equivalent alternative. It runs and passes — but collects
only the unittest-style subset (568 of 784 tests); the
pytest-fixture files contribute nothing under unittest.
Fix (Improve #1): reword to name pytest as the full suite.

#### F2 [LOW] Dogfood workflow comment cites a stale total
`.github/workflows/ghostslice-ci.yml` explains the 180,000
budget from the v0.24.0 sliced total (136,395). The budget
is still sane (current total 150,024 = 83%), but the
comment should carry the current measurement so the next
reader does not have to re-derive it. Fix (Improve #1):
append the v1.0.0 measurement to the comment.

#### F3 [INFO] L007 warns on the shipped completion scripts
Lint flags examples/completions/ghostslice.{bash,zsh} as
generated files included at full mode (1,599 + 1,312
estimated tokens). True — they ARE generated (the header
says so) — and warn-only; `ci` still exits 0. No action:
excluding them via a repo profile would change every
command's behaviour repo-wide, which G19 deliberately
avoided; the warning is the honest state.

#### F4 [INFO] `calls --dead` lists 10 candidates, all in
the tool's documented blind spots
Six are the example Lua plugin's contract functions
(invoked by the loader, not by project code), three are
the PluginAPI surface (called by user plugins), one is a
public textio helper. Zero are defects; the list carries
the standard "recommendations to review" caveat. No action.

#### Checked, no defect
- JSON stability: scan --json key set pinned by test and
  unchanged; no manifest or API payload touched.
- "estimated" labelling: the new scan table, summary box,
  fit table, and doctor header all keep the word; grep of
  the new surfaces confirms none lost it.
- Completions: bash -n and zsh -n both parse the shipped
  scripts; every subcommand + nested cache subcommands +
  flags come from the parser walk (test-pinned).
- Version sweep: no user-visible 0.24.0/0.16.0 remains
  outside CHANGELOG history and the roadmap log (the two
  example-action references were bumped to v1.0.0 in build).

## Improve #1
F1: README Tests wording now names pytest as the full suite
and describes unittest discover accurately (subset).
F2: dogfood workflow comment gains the v1.0.0 re-measurement
(150,024 = 83% of budget; no bump needed).

## Audit #2 — re-run + fresh probes
- Full command matrix re-run after Improve #1: identical
  result, every command exit 0 on both projects.
- Quickstart verbatim, pass 2: all five commands exit 0.
- Completions drift proof: a hypothetical parser subcommand
  (frobnicate/--zanzibar) added in-process appears in BOTH
  generated scripts with no generator change — the
  single-source-of-truth claim holds by construction, not
  by discipline.
- Scan with --model: the summary box carries the estimated
  input cost line with the local/dated prices label intact.
- Zero-token project (two empty files): table renders with
  empty heat bars and 0.0% shares, box intact, exit 0 — no
  division-by-zero anywhere in the new layout math.
- Doctor exit-code/payload agreement re-verified by the
  fixture battery (healthy 0, broken profile 1, broken
  prices 1, missing project 2).

### Findings
None new. No code changes resulted from Audit #2.

## Improve #2
No defects to fix. The round is spent on final verification:
the full suite green (below), `ghostslice secrets .` exit 0,
ROADMAP_20.md G20 marked done with the marathon-complete
line, and this audit closed.

## Final state
- Version 1.0.0 everywhere it lives: __init__, pyproject,
  dist metadata, MCP serverInfo, README examples.
- Tests: 784 passed, 1 skipped, 9 subtests (760 baseline +
  24 new); zero existing tests modified or weakened.
- Known limitations recorded in README: plugins are
  unsandboxed user code (G18 trust model), completions are
  generated-simple (subcommand + flag level), doctor's plugin
  check executes the load it verifies, unittest discover
  collects a subset of the suite.
