# GhostPrimer walkthrough

A five minute tour on a tiny sample project. Everything runs locally;
nothing here needs an account or a network.

Commands below use the installed `ghostprimer` entry point. From a
source checkout without installing, prefix each one the same way:
`PYTHONPATH=src python3 -m ghostprimer` instead of `ghostprimer`,
run from the repository root.

You will build three throwaway bundles along the way (the normal one,
a tiny-budget one, and one from a Recall bundle if you have one). All
of them go to `/tmp`, and step 8 explains why there is nothing to
undo.

## 1. Look at the project first

`examples/sample_project/` is a four file Python package called
demoapp: an entry point (`src/demoapp/main.py`), a greeter module it
imports, an unused module nothing imports, plus the project memory
files a real repo accumulates (`AGENTS.md`, `DECISIONS.md`,
`CHANGELOG.md`, `README.md`).

Keep the cast in mind while you read the pack:

| File | Role | Expected in the pack? |
|---|---|---|
| `src/demoapp/__init__.py` | package entry point | yes, signatures |
| `src/demoapp/main.py` | entry point | yes, signatures |
| `src/demoapp/greeter.py` | imported by the entry point (fan-in) | yes, signatures |
| `src/demoapp/unused.py` | imported by nothing, not an entry point | no, named in Not included |

## 2. Ask what a primer would find

```bash
ghostprimer doctor examples/sample_project
```

Doctor is read-only. It reports the project facts it can extract
(name `demoapp`, version, description), the entry points it found
(the `__init__.py` and `main.py` above), which memory sources exist
and which are missing (`AGENTS.md`, `DECISIONS.md`, and `CHANGELOG.md`
exist here; `CLAUDE.md`, `CONTRIBUTING.md`, `PLAN.md`, and roadmaps
do not), which token estimator is in use, and whether GhostSlice's
estimator is available. It writes nothing and does not predict a
budget outcome; it answers "what is here to prime from?"

## 3. Build the starter pack

```bash
ghostprimer build examples/sample_project -o /tmp/demo-primer
```

Expected output (token counts are estimates, so treat the exact
numbers as this-machine values):

```text
GhostPrimer bundle: /tmp/demo-primer
  files: 3 (114 sliced tokens, was 167)
  memory: 3 items via fallback (109 tokens)
  not included: 1, blocked: 0
```

The bundle is a folder, not an archive:

- `PRIMER.md` is the pack itself: extracted project facts, a
  start-here list, the README extract, the code slice (entry points
  and the modules they lean on, at signature depth), the memory
  primer, and a list of what was not included.
- `manifest.json` records every file and memory item with its token
  counts, sha256, mode, and provenance, plus the bundle totals.
- `files/` holds the sliced code at its original relative paths.

Useful variants of the same command:

```bash
# A label for this pack, recorded verbatim in the manifest.
# It does not change what is selected.
ghostprimer build examples/sample_project -o /tmp/demo-primer --task "first session"

# The build summary as one JSON object, for scripts.
ghostprimer build examples/sample_project -o /tmp/demo-primer --json
```

## 4. Read the pack like a new session would

Read `PRIMER.md` top to bottom. That is the whole point of the tool:
one small pack a new session, human or agent, reads whole on day
one. While you read, check the pack against the project:

- **Project facts** match `pyproject.toml`: name, version,
  description, the `demoapp` script, and the top-level layout.
- **Start here** lists the two entry points, before any other code.
- **Code slice** shows signatures, not bodies: you can see that
  `main.py` imports `greeting` from `greeter.py` and what each
  function takes and returns, without the implementation.
- **Project memory primer (source: fallback)** carries the standing
  rule from `AGENTS.md` ("Keep the greeting wording in greeter.py"),
  decision D-001 from `DECISIONS.md`, and only the latest entry from
  `CHANGELOG.md`, each headed with its source file and line.
- **Not included** names exactly one file: `src/demoapp/unused.py`,
  with the reason "unreferenced: no project file imports it and it
  is not an entry point". Nothing was dropped silently.

## 5. Check the pack

```bash
ghostprimer check /tmp/demo-primer
```

Check recomputes the file hashes and totals, verifies `PRIMER.md`
against the hash recorded in the manifest, and confirms every
recorded memory source path sits inside the project root and none
came from a private memory location. Exit codes: 0 pass, 1 fail
with reasons printed, 2 could not check (for example, no manifest).

Try it: edit one line of `/tmp/demo-primer/PRIMER.md` and run check
again. It exits 1 and names the `PRIMER.md` hash mismatch. Rebuild
to restore a clean pack.

## 6. Watch the budget ladder work

The default budget is 6,000 estimated tokens, far more than this
sample needs. Shrink it and the same project produces a thinner
pack instead of an error:

```bash
ghostprimer build examples/sample_project -o /tmp/demo-tiny --budget 60
```

On this sample that build keeps all 3 files but downgrades
`main.py` and `greeter.py` from signatures to outline, keeps only
the first memory item, and reports 3 not-included entries: the
unused module, plus the 2 memory items the spent memory share
could not hold. Push the
budget lower still and entry points are kept at outline even when
that breaks the budget; the build then prints a WARNING and the
manifest records `budget_unmet`. A starter pack that is honest
about not fitting beats no pack at all.

## 7. Feed it a GhostRecall bundle instead

Without one, the memory section comes from a shallow fallback pass
over the well-known files (headings plus capped extracts), and the
bundle says so: the section header and the manifest's `memory_path`
both read `fallback`. When a project has a real GhostRecall bundle,
pass it:

```bash
ghostprimer build <project> -o <bundle> --recall-bundle <recall-bundle-dir>
```

Primer then takes the bundle's current memory items verbatim, with
Recall's provenance, records `memory_path` as `recall-bundle`, and
never carries in superseded, excluded, or blocked items.

A previous session can be carried the same way, in addition to (not
instead of) the memory above:

```bash
ghostprimer build <project> -o <bundle> --handoff-pack <pack-dir-or-handoff.json>
```

The handoff's recorded state, open loops, and next steps appear in
their own labelled section and share the same memory budget. A pack
that names a different project is refused.

## 8. Undo

There is nothing to undo. A bundle is just a folder the tool wrote
where you told it to; delete it and the project is exactly as it
was. Primer never modifies the project it primes from.

## If something looks wrong

- **Build refused with a private-memory or outside-root message**:
  the path check is doing its job. A source resolved outside the
  project root, or into `~/MEMORY.md` / `~/memory/`, is never read;
  move or copy the project content inside the project instead of
  pointing Primer outward.
- **`WARNING: budget ... unmet`**: the pack was still written, with
  entry points at outline. Raise `--budget`, or accept the thinner
  pack knowing exactly what it kept; the limits section of
  `PRIMER.md` records the shortfall.
- **`check` exits 2**: the folder is not a readable bundle (usually
  a missing `manifest.json`). Point check at the folder `build`
  wrote, not at `PRIMER.md` itself.
