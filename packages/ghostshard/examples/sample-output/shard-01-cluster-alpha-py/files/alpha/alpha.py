"""Alpha subsystem: summarises alpha records. Self-contained.

Nothing in this module imports beta.py and nothing in beta.py
imports this module. The pair is the disjoint fixture: a planner
must be able to put them in one parallel group.
"""
import json


def parse_alpha_records(text):
    """Parse newline-delimited JSON alpha records."""
    records = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def alpha_total(records):
    """Sum the value field across alpha records."""
    total = 0
    for record in records:
        total += int(record.get("value", 0))
    return total


def alpha_summary(records):
    """Build the alpha summary mapping."""
    return {
        "count": len(records),
        "total": alpha_total(records),
        "kinds": sorted({str(r.get("kind", "unknown")) for r in records}),
    }


def format_alpha_summary(records):
    """Render the alpha summary as stable JSON text."""
    return json.dumps(alpha_summary(records), sort_keys=True)
