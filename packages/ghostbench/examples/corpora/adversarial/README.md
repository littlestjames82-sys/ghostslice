# Adversarial corpus

A tiny Python shop project built to be hard to bench well, bundled in
full under `project/`. The traps, also recorded per-task in `corpus.json`:

1. **Exact duplicate:** `project/shop/pricing.py` and
   `project/shop/pricing_copy.py` are byte-identical.
2. **Near duplicate:** `project/shop/rates_old.py` and
   `project/shop/rates_new.py` differ in only a few lines.
3. **Called but easy to exclude:** `project/shop/helpers.py` is small and
   generic-looking, but `router.py` imports `dispatch` and
   `dispatch_table` from it for every routing call. A slicer that drops
   it produces a bundle with a hard gap.
4. **Broken recorded patch:** `patches/broken-patch.diff` imports and
   calls `dispatch_v2`, which does not exist. Task adv-002 must surface
   as a visible failure in any correct Tier A report. A first published
   run of this corpus with zero failures anywhere means the corpus or
   the harness is wrong (PLAN.md verification bar).
5. **Superseded decision:** `project/DECISIONS.md` Decision 1 is
   SUPERSEDED by Decision 2. A Recall run serving Decision 1 as current
   fails task adv-003.

`patches/good-patch.diff` is the good recorded patch for adv-001.

## Run it

From the repository root:

```bash
ghostbench run examples/corpora/adversarial/corpus.json --out /tmp/bench-adv
cat /tmp/bench-adv/BENCH.md
```

Expected outcome: adv-001 passes on its recorded patch, adv-002
shows as a visible failure (broken patch plus a predicted hard
gap), adv-003 scores `unknown` in Tier A (it needs a Recall run to
score), and adv-004 has no recorded patch to score. A report with
zero failures anywhere means something is wrong with the run, not
that the corpus passed cleanly.
