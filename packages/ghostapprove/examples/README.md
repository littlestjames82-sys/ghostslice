# Examples

Four sample approval requests, one per GhostApprove source. All data is
fictional and safe: no real secrets, no real targets.

| File | Source | Risk | What is being asked |
|---|---|---|---|
| `seatbelt-request.json` | seatbelt | high | Run a cleanup script outside the project folder. Its payload names a side-effect file (`examples/SHOULD_NOT_EXIST_seatbelt.txt`) that the test suite uses to prove approving never executes anything: that file must never appear. |
| `ghostguard-request.json` | ghostguard | medium | Read one setting name from a config file that matched a secrets pattern (values are never in the request). |
| `ghostdeploy-request.json` | ghostdeploy | high | Deploy a release to an internal staging unit, with a diff summary. |
| `ghostbridge-request.json` | ghostbridge | low | Post a short status note to a shared board. |

## Try them

From the repository root, with a throwaway store, ingest any of them
(the id comes from the file, so each example can be ingested once per
store):

```bash
export PYTHONPATH=src
python3 -m ghostapprove --store /tmp/ga-examples ingest examples/seatbelt-request.json
python3 -m ghostapprove --store /tmp/ga-examples list
python3 -m ghostapprove --store /tmp/ga-examples show req-seatbelt-001
```

Then decide it by copying the full hash out of the `show` output into
an `approve` or `deny` command, exactly as in `WALKTHROUGH.md`. A
request can also be piped in on stdin instead of read from a file:

```bash
cat examples/ghostguard-request.json | python3 -m ghostapprove --store /tmp/ga-examples ingest -
```

## Write your own

Copy any file here and edit `action` (what is being asked) and
`summary` (why, in plain words). Change the `id` too, or remove it and
let ingest generate one: re-using an id that is already in the store
is refused. The full field list is in the main README, under
"The request file". Never put a raw secret value in a request; name a
secret by reference only.

See `WALKTHROUGH.md` for a full ingest, decide, and audit run using
two of these files.
