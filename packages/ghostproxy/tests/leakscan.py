"""Canary leak scanner for GhostProxy test runs.

Scans every file under a root (text or binary) for canary strings and
reports hits by canary label + file path only. Canary *values* are
never included in the output, matching the Ghost house rule that a
secret finding is path + type, never the secret itself.

Usable from tests and by hand:

    python3 tests/leakscan.py <folder> <canary-value> [<canary-value> ...]

Exit code 0 = no hits, 1 = at least one hit, 2 = usage error.
"""

from __future__ import annotations

import sys
from pathlib import Path


def scan_tree(root, canaries):
    """Return a list of (relative_path, canary_label) hits.

    ``canaries`` maps a short label (safe to print) to the canary
    value (never printed). Every file under ``root`` is read as bytes
    so binary outputs (logs, caches) are covered too.
    """
    root = Path(root)
    hits = []
    if not root.exists():
        return hits
    encoded = {label: value.encode("utf-8") for label, value in canaries.items() if value}
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    for path in files:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for label, needle in encoded.items():
            if needle in data:
                hits.append((str(path), label))
    return hits


def main(argv):
    if len(argv) < 3:
        print("usage: leakscan.py <folder> <canary-value> [<canary-value> ...]")
        return 2
    root = Path(argv[1])
    canaries = {f"canary-{i}": value for i, value in enumerate(argv[2:], start=1)}
    hits = scan_tree(root, canaries)
    for path, label in hits:
        print(f"LEAK: {label} found in {path}")
    if hits:
        print(f"{len(hits)} leak hit(s)")
        return 1
    print("no canary leaks found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
