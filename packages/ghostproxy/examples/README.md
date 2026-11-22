# GhostProxy examples

Everything here runs locally against a fake upstream. No API key,
no network calls beyond 127.0.0.1, no spend.

| File | What it is |
|---|---|
| `sample-project/` | A tiny project with one of everything: an entry point, a padded module whose body slicing drops, an exact duplicate pair, a lockfile, and a secrets-shaped file with a labelled fake value. |
| `profile.example.json` | A `.ghostslice.json` `proxy` section: localhost host, per-request budget. Copy it into a project root and edit the port if 8765 is taken. Body logging deliberately does not appear: it cannot be enabled from a profile file at all, only by an explicit `--log-bodies` flag when the proxy is started, and in v0.1 the ledger holds no bodies even then. |
| `request.example.json` | An Anthropic Messages-shaped request carrying GhostSlice context sections (`# File: ...` blocks), as an agent client would send it. |
| `expected-transform-map.example.json` | The shape of the per-request transform map the proxy records for a request like the one above: what was kept, downgraded, or dropped, with a reason per file. Token numbers are placeholders in the example; real maps carry estimates stamped with the estimator version. |
| `fake_upstream.py` | A stand-in upstream on 127.0.0.1 that answers with canned JSON, so you can watch a full round trip. |
| `setup-claude-code.sh` | Points Claude Code at the local proxy (`ANTHROPIC_BASE_URL`). |
| `undo-claude-code.sh` | The one-command undo: unsets the variable and returns Claude Code to the direct API address. |

## Five-minute demo (fake upstream, no key)

Run these from the GhostProxy repo root, with a GhostSlice checkout
next to it (`../ghostslice`), as in the main README. GhostSlice's
`src` is on the PYTHONPATH in the proxy and report commands: without
it the proxy still runs, but fail-open, passing everything through
unsliced, and the transform map described below will not appear.

```bash
# terminal 1: fake upstream
python3 examples/fake_upstream.py 9999

# terminal 2: the proxy, watching the sample project
PYTHONPATH=src:../ghostslice/src python3 -m ghostproxy serve \
  --host 127.0.0.1 --port 8765 \
  --upstream http://127.0.0.1:9999 --project examples/sample-project

# terminal 3: send the example request through the proxy
curl -s http://127.0.0.1:8765/v1/messages \
  -H "x-api-key: use-anything-this-is-local" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  --data @examples/request.example.json

# then look at what the proxy recorded
PYTHONPATH=src:../ghostslice/src python3 -m ghostproxy report \
  --project examples/sample-project
```

In the transform map for that request you should see
`local_secrets.py` dropped by the secrets guard, `dup_b.py` dropped
as a duplicate, and `package-lock.json` dropped as a lockfile,
while `app.py` is kept whole. That map is the inspectable record
the trust story in the main README rests on.
