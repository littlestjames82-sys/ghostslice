# GhostBus starter corpus (description)

GhostBus is the standing GhostSlice demo tree (the calibrated estimator
measures that tree at 129,555 tokens full vs 45,770 sliced; estimates, not
billed amounts). This corpus describes it for GhostBench without copying
its code into this repo, per the plan: Bench records a project by commit
hash or tree hash, it does not vendor the project in.

To use it, run GhostBench against `corpus.json` in this folder. Its
project `path` is a relative path (`../../../../ghostbus`) to the real
GhostBus checkout observed in this workspace at `~/workspace/ghostbus`
(package version 0.5.10, test command `node test.mjs`). The loader
stamps the project's tree hash when the corpus is loaded. The tasks
target the real modules `src/tools.mjs`, `src/core.mjs`,
`src/handler.mjs`, and `src/cli.mjs`. If your GhostBus checkout lives
somewhere else, record it in your own corpus with
`ghostbench add <corpus.json> --project <path> --id ghostbus` instead
of editing this starter.

No run of this corpus has been published yet. Any future `BENCH.md` from
it must carry the GhostSlice version, estimator version, and price table
date it was produced with.
