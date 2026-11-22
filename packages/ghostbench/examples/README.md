# Examples

Start with the adversarial corpus: it is the only example that is
fully self-contained, and it is the one the README Quickstart runs.

- `corpora/adversarial/` - the small adversarial project built for Bench,
  bundled in full: planted exact and near duplicates, a called file that is
  easy to wrongly exclude (`project/shop/helpers.py`), a broken recorded
  patch that must surface as a visible failure, and a superseded decision
  for Recall runs.
  Run it: `ghostbench run corpora/adversarial/corpus.json --out /tmp/bench-adv`
  (paths here are relative to this `examples/` folder; from the repo
  root use `examples/corpora/adversarial/corpus.json`).
  Expect a report that is **not** all-green, on purpose: task
  `adv-002-broken-patch-missing-symbol` must show as a visible
  failure, and `adv-003-recall-current-decision` scores `unknown` in
  Tier A. See `corpora/adversarial/README.md` for the five traps.
- `corpora/ghostbus/` - starter corpus description for GhostBus, the standing
  GhostSlice demo tree. External project, described, not copied in.
  Its project path points at a sibling GhostBus checkout
  (`../../../../ghostbus` from the corpus file), so it only runs
  where that checkout exists; see `corpora/ghostbus/README.md`.
  Where it does not, record your own checkout with `ghostbench add`
  instead of editing this starter.
- `corpus-template/` - copy-and-fill starting point for adding your own
  project as a corpus. Copy the folder, rename the corpus, point
  `projects[0].path` at your project, and replace the example task.
  The `description` field inside `corpus.json` walks through it.
- `runs/sample-tier-a-run-a/` and `runs/sample-tier-a-run-b/` - SAMPLE report
  pairs in the documented `bench-report.json` + `BENCH.md` format, for the
  compare mode. The numbers in these two folders are illustrative format
  examples, labelled SAMPLE in the files themselves. They are not measured
  bench results and must never be quoted as results.
  Try them: `ghostbench compare runs/sample-tier-a-run-a runs/sample-tier-a-run-b`
  (a run folder is accepted wherever a `bench-report.json` path is).
