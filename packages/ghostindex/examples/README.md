# GhostIndex examples

Two tiny projects and one captured session, so you can see what the
tool does before pointing it at your own checkouts.

| Folder | What it is |
|---|---|
| `project_alpha/` | A greeter module, a README, and a `scratch_notes.py` that the project's own `.gitignore` lists (so the index must skip it) |
| `project_beta/` | A ledger module and notes; it shares the phrase "sunflower festival" with alpha, so one search spans both projects |
| `sample_search_session.md` | A captured session: index both projects, search the shared phrase, search the ignored file's term (no matches), and show index stats |

Try it yourself from the repo root. From an installed checkout the
commands are `ghostindex ...`; from a source checkout prefix them
with `PYTHONPATH=src python3 -m ghostindex` instead. The `--db`
flag goes after the command name and points every command at the
same scratch database, so the demo never touches your real index:

```bash
ghostindex index examples/project_alpha examples/project_beta --db /tmp/demo-index.db
ghostindex search "sunflower festival" --db /tmp/demo-index.db
ghostindex search scratchterm --db /tmp/demo-index.db   # exit 1: never indexed
ghostindex stats --db /tmp/demo-index.db
```

What to notice in the output:

- The index run reports `scratch_notes.py` under "skipped by ignore
  rules": alpha's `.gitignore` names it, so its text is unsearchable
  by design, not by accident.
- The "sunflower festival" search returns hits from both projects
  in one ranked list, each with an excerpt and token estimates for
  the excerpt versus the whole file.
- The `scratchterm` search prints `no matches` and exits 1, which
  is the proof the ignored file stayed out of the index.

Search exit codes: 0 means matches, 1 means no matches, 2 means the
search could not run (for example, no index at that database path).
