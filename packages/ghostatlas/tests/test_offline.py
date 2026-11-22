"""Offline verification bar (PLAN.md): the generated HTML makes
zero network requests when opened, and contains no secret-shaped
string from the planted fixture.

Harness note (honest): this environment has no browser to observe
live network traffic, so the test enforces the preconditions that
make network requests impossible in a static file: no absolute
http(s) references anywhere, and no element or API that can reach
the network (external script / stylesheet / image / font, fetch,
XMLHttpRequest, WebSocket, EventSource, sendBeacon). A file with
none of those constructs cannot phone home when opened offline or
online. REPORT_B.md records this limitation.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import PLANTED_SECRET, requires_core

NETWORK_PATTERNS = [
    (r"https?://", "absolute http(s) URL"),
    (r"<script[^>]+src\s*=", "external script"),
    (r"<link[^>]+href\s*=", "external stylesheet/link"),
    (r"<img[^>]+src\s*=\s*[\"'](?!data:)", "non-data image source"),
    (r"@import", "CSS @import"),
    (r"url\s*\(\s*[\"']?(?!data:|#)", "CSS url() to a non-data target"),
    (r"\bfetch\s*\(", "fetch() call"),
    (r"XMLHttpRequest", "XMLHttpRequest"),
    (r"WebSocket", "WebSocket"),
    (r"EventSource", "EventSource"),
    (r"sendBeacon", "navigator.sendBeacon"),
]


@requires_core
def test_atlas_html_has_no_network_constructs(build, ground_truth: Path):
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    html = built.html
    assert html, "atlas.html was not produced"
    offenders = [
        label for pattern, label in NETWORK_PATTERNS if re.search(pattern, html, re.IGNORECASE)
    ]
    assert not offenders, f"Atlas HTML contains network-capable constructs: {offenders}"


@requires_core
def test_atlas_html_is_single_self_contained_file(build, ground_truth: Path, tmp_path: Path):
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    siblings = [
        p
        for p in built.html_path.parent.iterdir()
        if p.is_file() and p.suffix.lower() in {".js", ".css", ".png", ".jpg", ".svg", ".woff", ".woff2"}
    ]
    assert not siblings, (
        f"Atlas HTML depends on sibling asset files {siblings}; PLAN.md requires "
        "one self-contained file (ATLAS.md / atlas.json metadata aside)"
    )


@requires_core
def test_planted_secret_never_appears_in_outputs(build, secret_project: Path):
    built = build(secret_project)
    assert built.result.returncode == 0, built.result.stderr
    assert PLANTED_SECRET not in built.html
    assert PLANTED_SECRET not in built.atlas_md
    # Belt and braces: scan every file in the output directory
    # (the project copy itself legitimately contains the canary).
    for path in built.html_path.parent.rglob("*"):
        if path.is_file() and PLANTED_SECRET.encode() in path.read_bytes():
            raise AssertionError(f"planted secret leaked into build output file {path}")
