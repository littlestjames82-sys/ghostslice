# GhostRecall examples

## sample_project/

A tiny fictional demo shop with every GhostRecall source type:

- `DECISIONS.md` - four decisions in the documented format, including
  a standing rule pair (D-001 shipping cutoff, D-002 refunds) and a
  superseded pair (D-003 held the spring sale, D-004 lifted the hold).
- `docs/shipping-notes.md` - a freeform note (plain source).
- `CHANGELOG.md` - history source.
- `src/shop.py` - code whose comments cite the decisions, so the
  combined bundle has something to pair memory with.

### Try it

Run these from the repository root, with the CLI installed
(`pip install -e .`, see the top-level README). Without installing,
replace `ghostrecall` with `PYTHONPATH=src python3 -m ghostrecall`.

```bash
# Everything the project remembers, largest estimated cost first
ghostrecall scan examples/sample_project

# Ranked memory for a task, with token costs
ghostrecall recall examples/sample_project --task "When do orders ship?"

# Same ranking, plus what was NOT selected and why
ghostrecall recall examples/sample_project \
  --task "When do orders ship?" --explain

# Explain one item (id, exact title, or source path) for a task, as JSON
ghostrecall explain examples/sample_project decision-d-001-2026-01-15 \
  --task "When do orders ship?"

# Combined code + memory bundle under a 2,000 token budget
ghostrecall bundle examples/sample_project \
  --task "When do orders ship and who approves a refund?" \
  --fit 2000 -o /tmp/shop-bundle

# Verify the bundle against its manifest
ghostrecall check /tmp/shop-bundle
# OK: /tmp/shop-bundle matches its manifest
```

The `recall` run above prints (token counts are estimates):

```text
     53 est  score=0.0612 [pinned rule]  D-001 (2026-01-15) (DECISIONS.md)
     56 est  score=0.0000 [pinned rule]  D-002 (2026-02-01) (DECISIONS.md)
     28 est  score=0.0958  Shipping notes (docs/shipping-notes.md)
```

Note D-002: a pinned rule can score 0.0000 for the task wording and
still be selected, because pinning is not ranking. The bundle folder
holds `PROMPT.md`, `RECALL.md`, `manifest.json`, and the sliced items
under `files/`.

What to look for in the output:

- D-003 appears only as superseded (or not at all), D-004 is the
  current spring-sale decision.
- D-001 and D-002 are pinned standing rules: they show up even for a
  task whose words do not match them, and the manifest marks them
  pinned rather than TF-IDF ranked.
- Every memory item in `manifest.json` carries provenance: source
  file, line, and date.

## DECISIONS.example.md

A blank starter in the documented `DECISIONS.md` format. Copy it to
the root of a real project and fill it in.
