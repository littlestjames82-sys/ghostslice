"""Report view: shows normalized records as text lines."""
from shared_core import normalize_records


def build_report(records):
    """Build the plain-text report for records."""
    lines = []
    for record in normalize_records(records):
        lines.append(f"{record['name']}: {record.get('detail', '')}")
    return "\n".join(lines)
