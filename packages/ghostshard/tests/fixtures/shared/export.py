"""Export view: writes normalized records as delimited rows."""
from shared_core import normalize_records


def build_export(records):
    """Build the delimited export text for records."""
    rows = []
    for record in normalize_records(records):
        rows.append("|".join([record["name"], record.get("detail", "")]))
    return "\n".join(rows)
