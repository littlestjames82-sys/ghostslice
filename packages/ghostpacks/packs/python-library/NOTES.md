# Python Library pack - tuning notes

Status: unscored. No GhostBench report backs this pack yet, so its
savings are unmeasured. Run Bench Tier A on a stated reference project
before claiming any score in pack.json.

Choices:
- src/** at signatures: a library's surface is what an agent usually
  needs first; bodies can be pulled per task.
- tests/** at strip-tests: test names communicate coverage without
  shipping every assertion body into context.
- docs/** and notebooks at headings: orientation without full prose.
- Cache and build output ignored: __pycache__, tool caches, dist and
  build trees, coverage output, egg-info.
- L009 (lockfile in context) raised to error severity: lockfiles in a
  Python library context bundle are almost always waste.
- Budget is a default suggestion (60000), not a measured finding.
