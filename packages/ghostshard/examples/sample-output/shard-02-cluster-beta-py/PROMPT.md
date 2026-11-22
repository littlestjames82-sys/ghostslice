# Shard: cluster: beta.py

(generated) graph cluster owning: beta/beta.py

## beta/beta.py (full)

```
"""Beta subsystem: exports beta rows as CSV. Self-contained.

Nothing in this module imports alpha.py and nothing in alpha.py
imports this module. The pair is the disjoint fixture: a planner
must be able to put them in one parallel group.
"""
import csv
import io


def parse_beta_rows(text):
    """Parse CSV text into beta row dicts."""
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def beta_row_count(rows):
    """Count beta rows."""
    return len(rows)


def format_beta_csv(rows):
    """Render beta rows back to CSV text with a fixed header."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["name", "score"])
    writer.writeheader()
    for row in rows:
        writer.writerow({"name": row.get("name", ""), "score": row.get("score", "")})
    return out.getvalue()


def beta_export(text):
    """Full beta export: parse then render."""
    return format_beta_csv(parse_beta_rows(text))

```
