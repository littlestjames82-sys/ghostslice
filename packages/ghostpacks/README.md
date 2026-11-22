# GhostPacks
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostpacks/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostpacks/actions/workflows/ci.yml/actions)

**Shareable GhostSlice profile packs: stack knowledge as data.**

A good `.ghostslice.json` profile is earned knowledge: which folders
in a Next.js app are generated, which Django paths are migrations, how
a monorepo's packages should be sliced, which files are entry points.
GhostPacks gives that knowledge a format: a pack is a small,
human-readable folder of data (a manifest plus a GhostSlice profile
fragment) that can be shared, merged into a project, scored, and
removed cleanly.

By Ghost Developer Studio. Working name, companion #11 to GhostSlice.
Full plan: [PLAN.md](PLAN.md).

## Status

v0.1 (Oct 14, 2026). The core CLI, three starter packs, tests, and
examples described below are built and in this checkout; all three
starter packs are currently **unscored** (see their `NOTES.md`).
Nothing is published, pushed, or priced, and no paid layer is
decided.

## Quick start

No install step and no network: run the CLI from this checkout
against the bundled demo pack.

```bash
cd ghostpacks
PYTHONPATH=src python3 -m ghostpacks lint examples/demo-python-pack
# lint: OK - demo-python 0.1.0 (kind: context, unscored) [python]

PYTHONPATH=src python3 -m ghostpacks show examples/demo-python-pack
PYTHONPATH=src python3 -m ghostpacks list   # the starter packs in packs/
```

Then try a full merge and remove round-trip on a throwaway copy of
the fixture project: see `examples/README.md`. Every command also
has its own help, for example
`PYTHONPATH=src python3 -m ghostpacks merge --help`.

## Hard rules (v0.1)

- **Data only.** A pack contains JSON and text a human can read top to
  bottom in minutes. Any executable or script file in a pack folder
  fails `ghostpacks lint`. The manager never installs, downloads, or
  executes plugin code; a pack may *reference* a plugin that the user
  already has, and that is all.
- **Local only, no network.** No registry, no marketplace, no update
  checker, no telemetry. Packs arrive by local folder or a git clone
  the user made themselves, and live in a local library folder
  (`~/.ghostpacks/` by default).
- **Context packs, never policy packs.** Every manifest carries
  `kind: "context"`. GhostPacks settings tune what an agent *reads*
  (GhostSlice's job); they grant no permissions and evaluate no
  policy. Agent Seatbelt and the GhostGuard family own that layer.
- **Previewed, explicit, reversible merges.** `merge` shows the full
  profile diff and requires an explicit yes. `remove` restores the
  pre-merge profile from the recorded backup, or explains exactly why
  it cannot (for example because the user edited the profile since)
  instead of guessing.
- **Honest scores.** A pack with no GhostBench result is labelled
  **unscored** everywhere it is shown. A pack that claims a Bench
  score must contain the Bench report file it references, or it
  fails lint. Lint also opens the report and cross-checks it: the
  report must be a JSON object inside the pack folder (a `..` path
  or symlink pointing outside backs nothing), its `score` field must
  equal the claimed score, and it must name the reference project the
  score was measured on. An empty or mismatched report file backs
  no score.

## A pack

```
my-pack/
  pack.json       manifest
  profile.json    profile fragment in the exact .ghostslice.json schema
  bench-report.json   (only if the pack claims a Bench score)
  README.md       (optional, what the pack is for)
```

`pack.json`:

```json
{
  "id": "python-library",
  "version": "0.1.0",
  "kind": "context",
  "stack": ["python"],
  "ghostslice": ">=1.0,<2.0",
  "author": "Ghost Developer Studio",
  "date": "2026-10-14",
  "profile_file": "profile.json",
  "bench": {"score": 42.0, "report": "bench-report.json"}
}
```

`bench` is optional. Omit it and the pack is unscored. Include a
score and the referenced report file must exist in the pack, parse
as a JSON object, carry the same `score` value as the claim, and
name its `reference_project` (see `examples/bench-report.template.json`
for the report shape).

Field notes:

- `id`: lowercase letters, digits, `.`, `_`, `-` (for example
  `python-library`); `version`: three-part, like `0.1.0`;
  `date`: `YYYY-MM-DD`.
- `kind` must be exactly `"context"`; anything else fails lint.
- `stack` (also accepted as `stack_tags`) lists the stack tags
  shown by `list` and `show`.
- `ghostslice` is the GhostSlice version range the pack was tuned
  for; `doctor` warns, with the range printed, when the current
  GhostSlice falls outside it.
- The fragment file is always named `profile.json`; starter and
  generated packs also carry a `profile_file` manifest entry
  saying so, for readers and other tools.
- `name` and `description` are optional and purely informational
  (`description` is printed by `show` when present).

`profile.json` is a fragment of a GhostSlice profile: top-level keys
from the `.ghostslice.json` schema only (`ignore`, `modes`, `model`,
`budget_tokens`, `entry_points`, `preset`, `auto_shrink`, `redact`,
`plugins`, `lint`, `duplicates`, `ci`). An unknown key fails the
merge with the key named, matching GhostSlice's loud-validation
discipline. Paths in a pack must be relative; absolute paths fail
lint.

## Usage

Run from a checkout, no install step (the interface the test suite
targets, see `tests/conftest.py`):

```bash
cd ghostpacks
PYTHONPATH=src python3 -m ghostpacks lint  <pack-folder>
PYTHONPATH=src python3 -m ghostpacks show  <pack-folder>
PYTHONPATH=src python3 -m ghostpacks list
PYTHONPATH=src python3 -m ghostpacks merge <pack-folder> <project>
PYTHONPATH=src python3 -m ghostpacks remove <project> <pack-id>
PYTHONPATH=src python3 -m ghostpacks doctor [target]
PYTHONPATH=src python3 -m ghostpacks init-pack <project> -o <out-folder>
```

- `lint <pack>` validates a pack folder: manifest, `kind`, profile
  fragment against the live GhostSlice schema, no absolute paths,
  no executable or script files, and, if a score is claimed, the
  Bench report exists in the pack and its contents back the claim
  (matching score, named reference project).
- `list` lists the packs in the local library, one summary line
  each (or JSON with `--json`).
- `show <pack>` prints the pack summary, including its score or the
  word **unscored**. `<pack>` may be a folder path or a pack id
  found in the library.
- `merge <pack> <project>` previews the profile diff,
  asks for an explicit yes (`--yes` skips the prompt, the diff is
  still printed), then writes the merged
  `.ghostslice.json` and records provenance (pack id, version,
  source, date, profile hash) in `.ghostslice-packs.json` next to
  it. Sharing the profile plus that lockfile reproduces the setup.
  The two arguments may be given in either order. If the project
  and the pack set the same key differently, the merge stops on
  the conflict; `--force` lets the pack win.
- `remove <project> <pack-id>` reverses a merge from the
  recorded backup, or reports why it cannot reverse cleanly.
  `--force` restores the backup even if the profile was edited
  after the merge or later packs were merged on top.
- `doctor [target]` checks a pack folder (lint, GhostSlice range,
  freshness, Bench status, plugin references) or a project folder
  (profile and lockfile parse, recorded packs still lint, profile
  drift since the latest merge). With no target it checks the
  current folder. Out-of-range and stale findings are warnings
  with the range or date printed, never silent passes.
- `init-pack <project> -o <out>` drafts a pack from a tuned project profile
  (manifest skeleton plus fragment, absolute paths stripped). A
  draft still needs `lint` and a Bench run before it can claim a
  score.

Where packs are looked up (`list`, and `show` / `merge` when given
a pack id instead of a folder): `--library DIR` first, then
`$GHOSTPACKS_LIBRARY`, then `~/.ghostpacks/`, then the starter
packs bundled in this checkout's `packs/` folder.

Exit codes: `0` success, `1` lint failure, merge conflict, or a
declined / not-done operation, `2` usage or pack errors (the
message is printed, never a traceback).

## Starter packs

Three packs ship in `packs/` (see PLAN.md), Bench Tier A scored on
stated reference projects or labelled unscored:

- `python-library`: Python library layout conventions.
- `nextjs-typescript`: Next.js / TypeScript app conventions.
- `monorepo`: multi-package layout built on GhostSlice workspace
  detection.

A pack whose Bench result is embarrassing ships with the number
shown, or does not ship. No silent cherry-picking.

## Examples

`examples/` contains a small unscored demo pack
(`examples/demo-python-pack/`) and a two-file fixture project
(`examples/fixture-project/`) you can merge it into and remove it
from by hand. See `examples/README.md`.

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

The suite covers the PLAN.md verification bar: a tampered pack
containing an executable file fails lint, an unknown profile key
fails merge with the key named, merge/remove restores the pre-merge
GhostSlice export totals exactly, unscored packs are labelled, and a
claimed score without its Bench report fails lint. The round-trip
test uses the real GhostSlice exporter from the sibling
`~/workspace/ghostslice` checkout (override with `GHOSTSLICE_SRC`).

## If something fails

- **`lint` names an executable or script file in the pack.** That
  is the data-only rule working as intended: remove the file.
  Nothing in a pack is ever run, so nothing executable belongs in
  one.
- **`merge` names an unknown profile key.** The fragment uses a key
  outside the `.ghostslice.json` schema listed above. Fix the key
  name in `profile.json`; the merge writes nothing until the
  fragment validates.
- **`merge` stops on conflicts.** The project and the pack set the
  same key differently, and both values are printed. Edit one side,
  or re-run with `--force` to let the pack win.
- **`remove` refuses a clean reversal.** The message says why: the
  profile was edited after the merge, or later packs were merged
  on top. Remove the later packs first, restore by hand from the
  recorded backup, or use `--force` deliberately; `remove` never
  guesses.

## Out of scope (v0.1)

Hosted registry or marketplace, ratings, accounts, payments,
auto-updates, telemetry, pack signing, installing or executing
plugin code, and automatic (agent-initiated) merges. A human runs
merge.

## Honest notes

- Stack packs rot as frameworks release majors. Packs carry stack
  tags and dates, and `doctor` flags out-of-range use as a warning
  with the range printed, never a silent pass.
- Token and savings figures come from GhostSlice's estimator and a
  local, dated price table. They are estimates, labelled as such.
- A bad pack can silently worsen context for everyone who trusts
  it. Bench scoring, diff preview, and reversibility exist for that
  reason; read a pack before you merge it.

## License

MIT core, same pattern as GhostSlice, Agent Seatbelt, and Ghost
Hands. Pricing for any future maintained pack library is not
decided.

---
<!-- ghost-studio-footer -->
## More from Ghost Developer Studio

Ghost Developer Studio builds developer tools, AI-agent safety software, and practical apps, and sells by showing working software, not slide decks.

- [Roadmap board](https://github.com/littlestjames82-sys/ghost-roadmaps): where every studio product stands
- [Agent Seatbelt](https://github.com/littlestjames82-sys/agent-seatbelt): deterministic guardrails for AI coding agents
- [Ghost Hands](https://github.com/littlestjames82-sys/ghost-hands): governed, recorded, replayable agent hands
- [GhostSlice](https://github.com/littlestjames82-sys/ghostslice): agent context and prompt optimizer
- [GhostIDE](https://github.com/littlestjames82-sys/ghostide-android): fully offline AI code editor for Android
- [All studio projects](https://github.com/littlestjames82-sys?tab=repositories)
