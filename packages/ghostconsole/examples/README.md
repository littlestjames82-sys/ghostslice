# GhostConsole examples

`fixture_reports/` holds four small projects whose report files are
written in the exact shapes the sibling Ghost tools write, one project
per board state:

- `verified-proj/` - every tool has reported, everything ok, nothing
  pending. Lands in Verified.
- `attention-proj/` - GhostVerify's latest verdict is `gaps_found`
  with 3 hard gaps, and GhostApprove has 2 of 3 requests still
  pending. Lands in Attention.
- `stale-proj/` - GhostWatch's verdict is `stale`. Lands in Stale.
- `empty-proj/` - no Ghost reports at all. Renders a full set of
  "no report found" rows and lands in Stale. Absence is never an
  error.

`board.html` is the board rendered from these fixtures. Regenerate it
(or render your own projects) with:

```sh
./run_demo.sh
# or by hand:
PYTHONPATH=../src python3 -m ghostconsole build --root fixture_reports -o board.html
```

What to check when the board opens:

| Project | Expected column | Why |
| --- | --- | --- |
| `verified-proj` | Verified | Every present report is ok and fresh. |
| `attention-proj` | Attention | Verify verdict `gaps_found`, plus pending Approve requests. |
| `stale-proj` | Stale | Watch verdict is `stale`. |
| `empty-proj` | Stale | No reports at all; every row says "no report found". |

Note the fixture reports in this folder are *inputs* to the demo, not
live project state: when GhostConsole scans a real project that
happens to ship fixtures like these under `examples/` or `tests/`,
those rows are labelled "(fixture/example report)" and never place
the project. This demo points `--root` directly at the fixture set,
so each fixture folder is itself treated as a project.

The board is one self-contained HTML file: inline CSS, no JavaScript,
no external references. It works offline, forever, and can be archived
as evidence of report state at a point in time. To see the same model
without a browser, run
`PYTHONPATH=../src python3 -m ghostconsole summary --root fixture_reports`.
