# Try GhostMCP Doctor on the sample configs

Run these from the GhostMCP Doctor folder. You need Python 3.10 or
newer and nothing else. Nothing here connects to the internet, and
no sample config is modified by any command: Doctor is read-only.

The commands use the no-install form
(`PYTHONPATH=src python3 -m ghostmcpdoctor ...`). If you installed
the package with `pip install .`, the same commands work with the
prefix replaced by `ghostmcpdoctor`.

Every command below was run verbatim by Agent B on Oct 14, 2026
against the landed v0.1 core, and the outputs quoted are the real
outputs (paths abbreviated). One abbreviation applies throughout:
each scan summary is followed in real output by three standing
`note:` lines (read-only scan, env values never reported, and the
`MISSING-COMMAND` evidence note). Those lines are omitted from the
quoted blocks below to keep the findings visible.

## 1. A clean config passes clean

```bash
PYTHONPATH=src python3 -m ghostmcpdoctor scan examples/claude-code.mcp.json --out-dir /tmp/gmd-clean
echo $?
```

```
ghostmcpdoctor scan: 2 server(s) in 1 config(s), 0 finding(s) (exit 0)
```

Exit code 0. The report in `/tmp/gmd-clean/` lists both servers,
and lists the env key `FAKE_API_KEY` by name as present. Its fake
value appears nowhere in either report file:

```bash
grep -rn "FAKE-EXAMPLE" /tmp/gmd-clean/   # no matches
```

## 2. The same name in two clients is a duplicate

`cursor.mcp.json` defines `project-docs` again, with the same
definition as the Claude Code sample:

```bash
PYTHONPATH=src python3 -m ghostmcpdoctor scan examples/claude-code.mcp.json examples/cursor.mcp.json --out-dir /tmp/gmd-dup
echo $?
```

```
ghostmcpdoctor scan: 3 server(s) in 2 config(s), 1 finding(s) (exit 1)
  [warn] project-docs - examples/cursor.mcp.json - DUPLICATE: server name also defined in examples/claude-code.mcp.json
```

One finding for the extra definition, naming both config paths.
Doctor reports it; deciding which copy wins is your job, not its.

## 3. The messy config earns its findings

```bash
PYTHONPATH=src python3 -m ghostmcpdoctor scan examples/messy.mcp.json --out-dir /tmp/gmd-messy
echo $?
```

```
ghostmcpdoctor scan: 4 server(s) in 1 config(s), 3 finding(s) (exit 1)
  [warn] filesystem-everywhere - / - BROAD-FILESYSTEM: path argument grants a broad root: /
  [warn] filesystem-everywhere-again - / - BROAD-FILESYSTEM: path argument grants a broad root: /
  [error] gone-tool - examples/messy.mcp.json - MISSING-COMMAND: command not found: ghostmcp-nonexistent-binary-9f3k
```

Note what is *not* there: the fourth server, `key-holder`, produces
no finding and no leak. Its env keys are listed by name in the
report's server inventory as present; their fake values appear in
no output:

```bash
grep -rn "FAKE-EXAMPLE" /tmp/gmd-messy/   # no matches
```

## 4. Re-render a report without re-scanning

```bash
PYTHONPATH=src python3 -m ghostmcpdoctor report /tmp/gmd-messy/mcpdoctor-report.json --out-dir /tmp/gmd-rerender
```

```
wrote /tmp/gmd-rerender/mcpdoctor-report.json and /tmp/gmd-rerender/MCPDOCTOR.md
```

The re-rendered pair is the shareable artifact: it was redacted at
scan time, so there is nothing left in it to leak. The command
exits with the code recomputed from the stored findings (1 here,
because the messy scan had warnings and errors).

## 5. A print-only scan, for scripts

Add `--no-report` when you only want the summary (or, with `--json`,
the full report) on stdout and no files written:

```bash
PYTHONPATH=src python3 -m ghostmcpdoctor scan examples/claude-code.mcp.json --no-report
echo $?
```

```text
ghostmcpdoctor scan: 2 server(s) in 1 config(s), 0 finding(s) (exit 0)
```

(plus the three standing `note:` lines described at the top). The
process exit code is the scan's exit code, which is what a script
or CI job should check: 0, 1, or 2 as summarised below.

## Reading the reports

- `mcpdoctor-report.json` is the machine-readable form: configs
  scanned, the safe server inventory, findings with issue codes and
  severities, and a summary with stale and duplicate counts.
- `MCPDOCTOR.md` is the same data for humans: summary, per-config
  inventory, findings grouped for reading.
- Exit codes: 0 = scanned, nothing above info; 1 = warnings or
  errors found; 2 = could not scan at all.
