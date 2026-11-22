# GhostScope examples

## `run_demo.sh`

```bash
sh examples/run_demo.sh
```

Builds a local git repo in a temporary directory from
`tests/fixtures/high_blast_radius` (a base commit, then a one-line
change to `compute_total`, a function with 6 callers, plus a
220-line change to an isolated file) and runs `ghostscope pack`
on the `HEAD~1..HEAD` range. It uses an installed `ghostscope`
command if there is one, otherwise the checkout's `src/` layout
via `PYTHONPATH`.

Expected result: the pack's `REVIEW.md` is printed, and the
one-line `compute_total` change ranks first in the reading order,
ahead of the much larger isolated change, with its caller count
stated as a reason. The temporary directory, including the pack,
is removed when the script exits, so copy the pack path's contents
elsewhere during the run if you want to keep them.

If no core can be found at all, the script prints that expected
outcome instead and exits 3.

## `sample_pack/`

The documented *shape* of a finished pack (`scope.json`,
`REVIEW.md`). Hand-written samples, clearly labelled in the files
themselves, not captured run output. Use them to see the file
formats without running anything; use `run_demo.sh` for a real
pack.
