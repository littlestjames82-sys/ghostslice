# Data pack: customers.csv

Format: csv. Rows parsed: 6 of 6 total (0 malformed, counted and reported in manifest.json).
Sample: 6 rows (head + tail + evenly spaced middle) of 6 parsed rows. The sample is a sample, not the file.
Token estimates (estimates (BPE-like split v2, per-language calibrated, not exact tokenizer counts)): sample 132, full file 144.

## Schema (types inferred, not declared)

| column | type | null rate | distinct | notes |
|---|---|---|---|---|
| id | integer | 0.0 | 6 | min 1, max 6 |
| name | string | 0.0 | 6 |  |
| plan | string | 0.0 | 3 |  |
| seats | integer | 0.0 | 6 | min 1, max 12 |
| email | string | 0.0 | 6 | REDACTED: column name matches email |
| signup_date | date | 0.0 | 6 |  |

Redacted columns are shown as [REDACTED] in the sample. Reasons are recorded in manifest.json.

## Sample (files/customers.sample.csv)

```
id,name,plan,seats,email,signup_date
1,Ana Ruiz,starter,2,[REDACTED],2026-01-04
2,Ben Osei,pro,5,[REDACTED],2026-01-19
3,Cy Young,pro,3,[REDACTED],2026-02-02
4,Dee Lin,team,12,[REDACTED],2026-02-14
5,Eli Ford,starter,1,[REDACTED],2026-03-01
6,Fay Moss,team,8,[REDACTED],2026-03-09
```
