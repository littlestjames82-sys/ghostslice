# GhostHandoff examples: the fixture repo walkthrough

This walkthrough builds a small git repository in a known
mid-session state, packs a handoff from it, and shows what the pack
says. Everything is local; nothing leaves your machine.

**You need:** Python 3.10+, git on your PATH, and a way to run the
CLI: either an installed `ghosthandoff`, or, from the repo root,
`PYTHONPATH=src python3 -m ghosthandoff` wherever this walkthrough
says `ghosthandoff`.

**Time needed:** about two minutes. All commands run from this
`examples/` directory unless noted.

## 1. Build the demo repo

```sh
python3 make_fixture_repo.py ./demo-project
```

The script creates a repo with:

- branch `feature/handoff-fixture`
- an old commit dated 3 days before the demo is built (outside
  the default window), plus two fresh commits (inside it)
- one staged change (CHANGELOG.md), one unstaged change
  (README.md), one untracked file (scratch.py)
- one stash entry
- three markers: a TODO in pricing.py, a FIXME in app.py, a TODO
  in scratch.py
- a `verify-report.json` and `VERIFY.md` recording a failing
  GhostVerify verdict

Tip: run `git -C ./demo-project status` and
`git -C ./demo-project log --oneline` now, so you can check the
pack against git's own answers in step 3.

## 2. Pack the handoff

```sh
ghosthandoff pack ./demo-project -o ./pack-out
```

Output from a real run:

```text
Handoff pack written: ./pack-out/HANDOFF.md
Machine copy:         ./pack-out/handoff.json
Commits in window: 2, files touched: 7, markers: 3, reports: 2, open loops: 5, next steps: 6
```

Two files land in `./pack-out`, and nowhere else. The demo repo is
byte-identical afterwards; the test suite hashes the whole tree,
`.git` included, to prove it.

Re-running the same command exits 2, because the pack files already
exist. That is overwrite protection, not an error in your project:
add `--force` to replace the pack, or choose a new `-o` directory.

## 3. Read the pack

```sh
ghosthandoff show ./pack-out
```

The top of HANDOFF.md from the same run:

```text
# Handoff: demo-project

Drafted by GhostHandoff 0.1.0 from repo facts ... Propose-only:
nothing was committed, sent, or changed in the project. Every fact
names its source. Anything not found is stated as not found.

## State now
- Branch: feature/handoff-fixture (HEAD 832f9d8)
- Upstream: none recorded
- Working tree: 1 staged, 1 unstaged, 3 untracked
- Stash: 1 entry

## Changed this session
Window: last 12 hours (default) plus all uncommitted changes
- Commits in window: 2
  - 832f9d8 Wire pricing into the app entry point (Fixture Dev, ...)
  - 178cefa Add pricing module (Fixture Dev, ...)
```

(Commit hashes and timestamps differ per run; the shape does not.)

What to check against the repo you just built:

- The two in-window commits are listed; the 3-day-old commit is
  not. Run `git log --oneline` in demo-project and compare.
- The verification section quotes the failing verdict from
  verify-report.json with the file's modification time. Nothing
  was re-run to get it.
- Open loops counts five: uncommitted work, untracked files, the
  stash entry, the open markers, the failing verdict. Each names
  its source.
- Next steps are drafted from those loops, in a fixed order, each
  citing the fact it came from. They are proposals for the next
  session to confirm, not instructions the tool carried out.

For the machine-readable twin, skim `./pack-out/handoff.json`:
the same facts live under `git`, `markers`, `reports`,
`open_loops`, and `next_steps`, and its counts match the Markdown
exactly because both files are rendered from one dict.

## 4. Widen the window

A duration window is relative to *now*, and the demo's old
commit is dated 3 days before the demo is built. Pick a duration
that comfortably spans that gap; 30 days always works for this
demo:

```sh
ghosthandoff pack ./demo-project -o ./pack-wide --since 30d
```

Now the 3-day-old commit is inside the window and appears in the
session commits. `--since` also accepts an ISO date
(`--since 2026-10-01`) or a git ref (then the session is
`ref..HEAD`, for example `--since HEAD~3`).

## 5. A folder that is not a repo

```sh
mkdir plain && printf 'notes\nTODO: water the plants\n' > plain/notes.txt
ghosthandoff pack ./plain -o ./pack-plain
```

Still exit 0. The git section reads "unavailable", and the marker
in notes.txt is still found and listed. A handoff pack degrades
with a label instead of failing when git facts are absent.

## Clean up

```sh
rm -rf ./demo-project ./pack-out ./pack-wide ./plain ./pack-plain
```

Nothing outside this directory was written, so that removes the
whole demo.
