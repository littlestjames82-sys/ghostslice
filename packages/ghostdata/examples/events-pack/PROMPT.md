# Data pack: events.jsonl

Format: jsonl. Rows parsed: 5 of 5 total (0 malformed, counted and reported in manifest.json).
Sample: 5 rows (head + tail + evenly spaced middle) of 5 parsed rows. The sample is a sample, not the file.
Token estimates (estimates (BPE-like split v2, per-language calibrated, not exact tokenizer counts)): sample 240, full file 245.

## Schema (types inferred, not declared)

| column | type | null rate | distinct | notes |
|---|---|---|---|---|
| ts | date | 0.0 | 5 |  |
| event | string | 0.0 | 3 |  |
| user_id | integer | 0.0 | 4 | min 101, max 104 |
| api_token | string | 0.0 | 4 | REDACTED: column name matches token |

Redacted columns are shown as [REDACTED] in the sample. Reasons are recorded in manifest.json.

## Sample (files/events.sample.jsonl)

```
{"ts": "2026-03-01T09:00:00", "event": "login", "user_id": 101, "api_token": "[REDACTED]"}
{"ts": "2026-03-01T09:02:00", "event": "export", "user_id": 102, "api_token": "[REDACTED]"}
{"ts": "2026-03-01T09:05:00", "event": "login", "user_id": 101, "api_token": "[REDACTED]"}
{"ts": "2026-03-01T09:11:00", "event": "delete", "user_id": 103, "api_token": "[REDACTED]"}
{"ts": "2026-03-01T09:20:00", "event": "export", "user_id": 104, "api_token": "[REDACTED]"}
```
