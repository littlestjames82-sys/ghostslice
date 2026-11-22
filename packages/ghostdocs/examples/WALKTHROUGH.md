# Try GhostDocs on the sample help centre

A tiny made-up document set lives in `sample-help-centre/`. It holds two
versions of a returns policy on purpose: the 2024 page says 30 days, the
2026 page says 45 days, and they are otherwise almost the same page. That
is exactly the kind of quiet duplication GhostDocs exists to find.

Run these from the GhostDocs folder. You need Python 3.10 or newer and
nothing else. Nothing here connects to the internet. The sample writes
its outputs to `/tmp`, so your document folders are never touched; on
a system without `/tmp`, replace those paths with any folder you like.

## 1. Look at the document set

```bash
PYTHONPATH=src python3 -m ghostdocs scan examples/sample-help-centre
```

What to look for in the output:

- The returns pages are grouped as a duplicate cluster.
- The 2026 page is named the probable current one, because it is the
  newest dated. That is a best guess by date, not a fact. Check it.
- An estimate of how many tokens the repeats are wasting.

Try `scan --json` for the same result as machine-readable JSON, or
`scan --top 2` to shorten the heat list to the two largest documents:

```bash
PYTHONPATH=src python3 -m ghostdocs scan examples/sample-help-centre --json
```

## 2. Make an export for an assistant

```bash
PYTHONPATH=src python3 -m ghostdocs export examples/sample-help-centre -o /tmp/help-centre-export
```

The export folder contains a ready-to-send bundle (`PROMPT.md` and
`files/`), a list of exactly what went in (`manifest.json`), and a
`chunks.jsonl` file for tools that load knowledge in pieces. The old
2024 returns page is left out, because the sample settings file
(`.ghostdocs.json` in the sample folder) says older versions are kept
out of exports but still shown in reports. The command output says so
too, on a `Superseded skipped:` line.

To export only the material relevant to one topic instead, add a
task. Only sections that match it are kept:

```bash
PYTHONPATH=src python3 -m ghostdocs export examples/sample-help-centre -o /tmp/help-centre-returns --task "returns and refunds"
```

## 3. Read the plain-words report

```bash
PYTHONPATH=src python3 -m ghostdocs report examples/sample-help-centre -o /tmp/help-centre-report.html
```

Open the HTML file in any browser. It works offline. It lists the
duplicates, the older versions, anything held back, and anything
GhostDocs could not read.

## 4. Check an export

```bash
PYTHONPATH=src python3 -m ghostdocs check /tmp/help-centre-export
```

This confirms the files in the export match the manifest list, so what
you think you sent is what you actually sent. A good bundle prints:

```text
Bundle OK: hashes and totals match manifest.
```

If a file in the export folder is edited or removed afterwards, the
check names the problem and exits with code 1 instead.
