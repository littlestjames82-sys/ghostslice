# GhostSlice Monorepo

As of Nov 22, 2026, the GhostSlice family lives in this one repository.

## Layout

- **Root** — GhostSlice itself (`ghostslice` 1.0.6): the agent context and
  prompt optimizer. Unchanged from the former standalone core repo.
- **packages/** — the companion tools, each a self-contained, independently
  packageable Python project: its own `pyproject.toml`, `src/` layout,
  tests, and console script, byte-for-byte as in its own repo.

## Packaging

Every package still builds and installs on its own, exactly as before:

```sh
python -m build packages/ghostpacks          # wheel + sdist for one tool
pip install ./packages/ghostpacks            # or install it directly
```

This was verified before the move: for every package, the wheel built
from this monorepo is identical in contents to the wheel built from its
former standalone repo, and the built wheel imports cleanly.

| Folder | Package | Version | Files |
|---|---|---|---|
| `packages/ghostatlas/` | ghostatlas | 0.1.0 | 47 |
| `packages/ghostapprove/` | ghostapprove | 0.1.0 | 39 |
| `packages/ghostbench/` | ghostbench | 0.1.0 | 65 |
| `packages/ghostconsole/` | ghostconsole | 0.1.0 | 62 |
| `packages/ghostconsole-app/` | ghostconsole-app | 0.1.0 | 25 |
| `packages/ghostconvert/` | ghostconvert | 0.1.0 | 58 |
| `packages/ghostdata/` | ghostdata | 0.1.1 | 54 |
| `packages/ghostdeps/` | ghostdeps | 0.1.0 | 44 |
| `packages/ghostdocs/` | ghostdocs | 0.1.0 | 51 |
| `packages/ghostenv/` | ghostenv | 0.1.0 | 52 |
| `packages/ghostexposure/` | ghostexposure | 0.1.0 | 57 |
| `packages/ghostfixture/` | ghostfixture | 0.1.0 | 84 |
| `packages/ghosthandoff/` | ghosthandoff | 0.1.0 | 39 |
| `packages/ghostindex/` | ghostindex | 0.1.0 | 59 |
| `packages/ghostleads/` | ghostleads | 0.1.0 | 41 |
| `packages/ghostledger/` | ghostledger | 0.1.0 | 43 |
| `packages/ghostlift/` | ghostlift | 0.1.0 | 51 |
| `packages/ghostlogs/` | ghostlogs | 0.1.0 | 41 |
| `packages/ghostmcp/` | ghostmcp | 0.4.0 | 22 |
| `packages/ghostmcpdoctor/` | ghostmcpdoctor | 0.1.0 | 48 |
| `packages/ghostpacks/` | ghostpacks | 0.1.0 | 46 |
| `packages/ghostport/` | ghostport | 0.1.0 | 104 |
| `packages/ghostprimer/` | ghostprimer | 0.1.0 | 87 |
| `packages/ghostproxy/` | ghostproxy | 0.1.0 | 50 |
| `packages/ghostrecall/` | ghostrecall | 0.1.0 | 62 |
| `packages/ghostrecipes/` | ghostrecipes | 0.1.0 | 35 |
| `packages/ghostreplay/` | ghostreplay | 0.1.0 | 68 |
| `packages/ghostreview/` | ghostreview | 0.1.0 | 73 |
| `packages/ghostschema/` | ghostschema | 0.1.0 | 54 |
| `packages/ghostscope/` | ghostscope | 0.1.0 | 64 |
| `packages/ghostshard/` | ghostshard | 0.1.0 | 68 |
| `packages/ghostverify/` | ghostverify | 0.1.0 | 58 |
| `packages/ghostwatch/` | ghostwatch | 0.1.0 | 43 |
| `packages/ghostworkflow/` | ghostworkflow | 0.1.0 | 26 |
| `packages/ghostworktree/` | ghostworktree | 0.1.0 | 40 |

## Core dogfood scope

The core's dogfood checks (its CI checks, token budget, and dead-code
scan) analyse this repo root. A `packages/` entry in the root
`.gitignore` scopes those runs to the core tree, exactly as they ran in
the standalone repo — the scanner honours `.gitignore`. The packages
are tracked in git and unaffected; each keeps its own tests and gate.

## Original repos

The former standalone repos for the packages above are archived on
GitHub (archived repos are read-only; GitHub's Public archive banner is
the pointer). Nothing was deleted.

By Ghost Developer Studio.
