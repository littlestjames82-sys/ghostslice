# Ground-truth fixture

`project/` is a deliberately tiny application whose structure is known
exactly, so GhostAtlas output can be checked against stated truth
(`TRUTH.json`) instead of against the tool's own claims:

- Entry point: `main.py` (carries a `__main__` guard, imports `engine`).
- Known graph edges: `main.py -> engine.py`, `engine.py -> util.py`,
  `test_engine.py -> engine.py`.
- Most depended-on module: `engine.py` (imported by `main.py` and
  `test_engine.py`).
- Known dead file: `dead.py`. Nothing imports it, nothing calls it.
  Atlas must list it in its dead zones ("worth asking about"), and must
  never present it as an entry point or a depended-on module.
- `settings.json` is the fixture's only config/data file.
- `README.md` is the fixture's only prose doc.
