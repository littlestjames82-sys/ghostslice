# Walkthrough

A complete GhostApprove run: two requests in, one approval, one denial,
one refused double decision, and the audit trail. The commands below
are run from the repository root against a throwaway store at
`/tmp/ga-walk`.

The hashes are content hashes, so re-running this on the unchanged
example files reproduces the same hashes. The timestamps below are
from one real run; on your run the timestamps (and the `age` fields
derived from them) will differ, and everything else will match.

```bash
export PYTHONPATH=src

# 1. Ingest two requests
python3 -m ghostapprove --store /tmp/ga-walk ingest examples/ghostbridge-request.json
# ingested: req-ghostbridge-001
#   source: ghostbridge  risk: low
#   action: Post a short build-status note to the shared board at board/studio-status
#   hash:   add7e122a394fe3eb2969fbeab5d1ec83a776d63aaed275b54abcd8c331c7ca7
#   status: pending (recorded; nothing decided, nothing executed)

python3 -m ghostapprove --store /tmp/ga-walk ingest examples/ghostdeploy-request.json
# ingested: req-ghostdeploy-001
#   source: ghostdeploy  risk: high
#   action: Deploy release 2026.10.14-1 to the internal staging unit staging/ghostslice-companions
#   hash:   fd7f7d7129903f4c244355991e44d15a9f8f892bfbaeca946d681f9e35170496
#   status: pending (recorded; nothing decided, nothing executed)

# 2. The queue, oldest first, short hashes on the list view
python3 -m ghostapprove --store /tmp/ga-walk list
# req-ghostbridge-001  [pending]  ghostbridge  risk=low  age=just now  hash=add7e122a394  Post a short build-status note to the shared board at board/studio-status
# req-ghostdeploy-001  [pending]  ghostdeploy  risk=high  age=just now  hash=fd7f7d712990  Deploy release 2026.10.14-1 to the internal staging unit staging/ghostslice-companions

# 3. Show one request in full before deciding (full hash, summary, payload)
python3 -m ghostapprove --store /tmp/ga-walk show req-ghostbridge-001
# id:     req-ghostbridge-001
# status: pending
# source: ghostbridge
# risk:   low
# action: Post a short build-status note to the shared board at board/studio-status
# summary: Keep the board current after the Wave 3 build dispatch.
# requested_by: bridge-relay
# ingested_at: 2026-10-18T18:51:33.335Z
# age:    just now
# hash:   add7e122a394fe3eb2969fbeab5d1ec83a776d63aaed275b54abcd8c331c7ca7
# payload:
# {
#   "board": "board/studio-status",
#   "note": "Wave 3 build dispatched: 10 tools, 20 agents."
# }

# 4. Decide, naming the exact hash from show
python3 -m ghostapprove --store /tmp/ga-walk approve req-ghostbridge-001 \
  --hash add7e122a394fe3eb2969fbeab5d1ec83a776d63aaed275b54abcd8c331c7ca7 \
  --by ryan --note "ok to post"
# approved: req-ghostbridge-001
#   hash: add7e122a394fe3eb2969fbeab5d1ec83a776d63aaed275b54abcd8c331c7ca7
#   by:   ryan at 2026-10-18T18:52:09.607Z
#   note: ok to post
#   decision recorded only - GhostApprove did NOT execute this action

python3 -m ghostapprove --store /tmp/ga-walk deny req-ghostdeploy-001 \
  --hash fd7f7d7129903f4c244355991e44d15a9f8f892bfbaeca946d681f9e35170496 \
  --by ryan --note "not yet"
# denied: req-ghostdeploy-001
#   hash: fd7f7d7129903f4c244355991e44d15a9f8f892bfbaeca946d681f9e35170496
#   by:   ryan at 2026-10-18T18:52:10.564Z
#   note: not yet
#   decision recorded only - GhostApprove did NOT execute this action

# 5. A second decision on a decided request is refused (exit 1, nothing written)
python3 -m ghostapprove --store /tmp/ga-walk approve req-ghostbridge-001 \
  --hash add7e122a394fe3eb2969fbeab5d1ec83a776d63aaed275b54abcd8c331c7ca7 --by ryan
# refused: request req-ghostbridge-001 is already approved; a second decision is refused, nothing recorded

# 6. Audit: the append-only history, in order
python3 -m ghostapprove --store /tmp/ga-walk history
# 2026-10-18T18:51:33.335Z  ingested  req-ghostbridge-001  hash=add7e122a394
# 2026-10-18T18:51:33.713Z  ingested  req-ghostdeploy-001  hash=fd7f7d712990
# 2026-10-18T18:52:09.607Z  approved  req-ghostbridge-001  hash=add7e122a394 by ryan note=ok to post
# 2026-10-18T18:52:10.564Z  denied  req-ghostdeploy-001  hash=fd7f7d712990 by ryan note=not yet
```

What to notice:

- Approving the bridge note did not post anything. Denying the deploy
  did not touch staging. GhostApprove only wrote two ledger lines.
- The store afterwards is exactly two record files plus the ledger:
  `/tmp/ga-walk/requests/req-ghostbridge-001.json`,
  `/tmp/ga-walk/requests/req-ghostdeploy-001.json`, and
  `/tmp/ga-walk/ledger.jsonl`. The record files are byte-identical
  before and after the decisions; decisions live only in the ledger.
- Try approving with one hex digit of the hash changed: refused, exit
  1, and the ledger does not grow. The test suite covers that, the
  stored-record tamper case, and the deny path in
  `tests/test_decisions.py`.
- The main README has a table of the other refusals an operator is
  likely to meet ("Common refusals and what they mean"), including
  what a damaged store looks like and how it fails closed.
