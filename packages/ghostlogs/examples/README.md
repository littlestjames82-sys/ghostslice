# GhostLogs examples

`billing-api.log` is a small synthetic log from a fictional billing
service: 33 lines in total. Two lines repeat:

- a poll line, 15 identical copies (lines 2-16), which collapses to
  one duplicate group;
- a warning line, 6 copies in total (lines 17-22): 5 of them
  collapse to a second duplicate group, and the 6th (line 22) is
  kept as context inside the error window instead, because the
  window opens three lines before its match.

There is also one gateway error with a Python traceback. The error
line carries a fake AWS-shaped key so the redaction is visible in
the pack. It is not a real credential and never was.

`incident-pack/` is what the tool produced from it, with this
command run from the repo root:

```
PYTHONPATH=src python3 -m ghostlogs pack examples/billing-api.log -o examples/incident-pack --budget 2000
```

Result, as printed by the tool (the estimator name in parentheses
depends on whether GhostSlice is reachable on your machine; the
manifest records which method was used):

```
Packed examples/billing-api.log -> examples/incident-pack
  lines 33 = kept 15 + collapsed 18 + dropped 0 (reconciles: True)
  windows: 1 emitted of 1 matched; duplicate groups: 2 emitted of 2
  pack estimate 708 tokens against budget 2000 (estimator: ...)
  budget tier: full - Every selected window and duplicate exemplar is shown in full.
  redactions: 1 {'aws-access-key': 1}
```

The estimate counts the pack exactly as written, header source path
included, so packing the same log through a longer path string gives
a slightly higher estimate. The counts and the redaction do not
change.

Open `incident-pack/INCIDENT.md` to see the pack an agent would read:
the timeline anchors, the error window with its context and
traceback, the repeated lines shown once each with exact counts
under "Repeated lines: 2 of 2 duplicate groups emitted", and a "What
was not shown" section stating the dropped counts by reason. The
fake key appears nowhere; in its place the window shows
`[REDACTED:aws-access-key]`.
`incident-pack/manifest.json` carries the same counts in machine
form, the source hash, the budget tier and its plain-words meaning
(`budget_tier` / `budget_tier_meaning`), the redaction counts by
shape, and the limits of the pack stated in writing.

To try a tighter budget:

```
PYTHONPATH=src python3 -m ghostlogs pack examples/billing-api.log -o /tmp/pack-tight --budget 300
```

At 300 tokens even the mandatory timeline anchors do not fit: the
tool ships the anchors tier (estimate 506 tokens on this path),
marks the pack over budget in the manifest and in a Pack status
section in `INCIDENT.md`, counts the other 31 lines as dropped, and
exits with code 1 rather than pretending it fit. Raise the budget
and the windows and duplicate exemplars come back, each step down
the tier ladder recorded in the manifest.
