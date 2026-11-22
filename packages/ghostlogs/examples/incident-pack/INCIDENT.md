# Incident pack: billing-api.log

Source: examples/billing-api.log (1894 bytes, sha256 424c75b5f5bf..., 33 lines, estimated 678 tokens in full).
Token budget: 2000. Estimator: estimates (BPE-like split v2, per-language calibrated, not exact tokenizer counts).
Counts: 33 lines in = 15 kept + 18 collapsed + 0 dropped (routine 0, duplicate exemplars not emitted 0, windows not fitted 0, window store cap 0).

## Timeline anchors

- First line (line 1): 2026-10-13T22:14:01Z INFO  billing-api boot build=1043
- Last line (line 33): 2026-10-13T22:18:00Z INFO  billing-api shutdown clean
- First timestamp: 2026-10-13T22:14:01Z (line 1)
- Last timestamp: 2026-10-13T22:18:00Z (line 33)

## Error windows (1 emitted of 1 matched)

### Lines 22-33: matched error-level at line 25 (severity 2)

```
2026-10-13T22:15:00Z WARN  retry budget low for gateway stripe
2026-10-13T22:16:40Z INFO  charge attempt id=ch_8812 amount=49.00
2026-10-13T22:16:40Z INFO  gateway request sent
2026-10-13T22:16:41Z ERROR gateway auth rejected key=[REDACTED:aws-access-key]
Traceback (most recent call last):
  File "billing/gateway.py", line 141, in charge
    resp = client.post(url)
billing.errors.GatewayAuthError: 401 from gateway
2026-10-13T22:16:42Z INFO  charge attempt id=ch_8812 status=failed
2026-10-13T22:17:00Z INFO  failover to secondary gateway
2026-10-13T22:17:03Z INFO  charge attempt id=ch_8813 status=ok
2026-10-13T22:18:00Z INFO  billing-api shutdown clean
```

## Repeated lines: 2 of 2 duplicate groups emitted (counts exact)

- x15 (byte-identical x15), lines 2-16: 2026-10-13T22:14:05Z INFO  poll ok queue=payments depth=0
- x5 (byte-identical x5), lines 17-21: 2026-10-13T22:15:00Z WARN  retry budget low for gateway stripe

## What was not shown

- Routine lines dropped: 0
- Duplicate occurrences, exemplar not emitted: 0
- Window lines not fitted: 0
- Window lines past the storage cap: 0
- Secret-shaped literals in emitted excerpts were redacted by shape; counts are in manifest.json. Values are never printed.
