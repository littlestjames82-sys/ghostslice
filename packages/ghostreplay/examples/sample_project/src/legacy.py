"""Legacy report writer. Nothing in the planted-waste sessions uses it.

Kept in the bundle at full mode so GhostReplay has a concrete
never-referenced file with a known manifest token count.
"""


def write_report(rows: list) -> str:
    lines = ["LEGACY REPORT"]
    for row in rows:
        lines.append(str(row))
    return "\n".join(lines)
