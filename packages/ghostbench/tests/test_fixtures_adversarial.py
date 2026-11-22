"""The adversarial corpus must actually contain its planted traps.
If a trap rots (someone 'fixes' the fixture), these tests fail loudly,
because a bench whose adversarial corpus has gone soft proves nothing.
"""

import hashlib
import re
from pathlib import Path

from conftest import EXAMPLES

ADV = EXAMPLES / "corpora" / "adversarial"
SHOP = ADV / "project" / "shop"


def _lines(path):
    return set(Path(path).read_text().splitlines())


def test_exact_duplicate_is_byte_identical():
    a = (SHOP / "pricing.py").read_bytes()
    b = (SHOP / "pricing_copy.py").read_bytes()
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()
    assert a == b and len(a) > 200


def test_near_duplicate_similarity_is_in_the_detectable_band():
    a, b = _lines(SHOP / "rates_old.py"), _lines(SHOP / "rates_new.py")
    jaccard = len(a & b) / len(a | b)
    # GhostSlice near-duplicate detection threshold is Jaccard >= 0.85.
    assert a != b, "near-duplicates must not be exact duplicates"
    assert jaccard >= 0.85, f"line Jaccard {jaccard:.2f} below Slice threshold"


def test_called_but_easy_to_exclude_file_is_really_called():
    helpers = (SHOP / "helpers.py").read_text()
    router = (SHOP / "router.py").read_text()
    assert "def dispatch(" in helpers and "def dispatch_table(" in helpers
    assert "from .helpers import" in router
    assert "dispatch(" in router and "dispatch_table(" in router
    # Small and generic-looking is the trap: it must stay small.
    assert len(helpers.splitlines()) < 25


def test_broken_patch_references_a_symbol_that_does_not_exist():
    patch = (ADV / "patches" / "broken-patch.diff").read_text()
    helpers = (SHOP / "helpers.py").read_text()
    added = [line[1:] for line in patch.splitlines() if line.startswith("+")]
    assert any("dispatch_v2" in line for line in added)
    assert "dispatch_v2" not in helpers, (
        "broken patch trap rotted: dispatch_v2 now exists in helpers.py")


def test_good_patch_applies_to_real_file_content():
    patch = (ADV / "patches" / "good-patch.diff").read_text()
    removed = [line[1:].strip() for line in patch.splitlines()
               if line.startswith("-") and not line.startswith("---")]
    helpers_lines = {line.strip() for line in (SHOP / "helpers.py").read_text().splitlines()}
    assert removed, "good patch removes nothing"
    for line in removed:
        assert line in helpers_lines, f"good patch line not in helpers.py: {line}"


def test_superseded_and_current_decisions_are_both_present_and_labelled():
    decisions = (ADV / "project" / "DECISIONS.md").read_text()
    assert "STATUS: SUPERSEDED" in decisions
    assert "STATUS: CURRENT" in decisions
    # The superseded decision must come with its replacement named.
    assert re.search(r"SUPERSEDED by Decision 2", decisions)
