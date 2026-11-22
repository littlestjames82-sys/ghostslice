"""Fixture validity: the planted terms the CLI tests rely on are
really where the tests think they are. These run without the core."""
from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ALPHA = FIXTURES / "project_alpha"
BETA = FIXTURES / "project_beta"
OUTSIDE = FIXTURES / "outside_project"


def test_alpha_auth_has_shared_and_unique_terms():
    text = (ALPHA / "src" / "auth.py").read_text()
    assert "Quixotic login handler validates session tokens" in text
    assert "handle_quixotic_login" in text


def test_beta_payments_has_shared_and_beta_only_terms():
    text = (BETA / "src" / "payments.py").read_text()
    assert "Quixotic billing reconciler" in text
    assert "betaonlyterm" in text
    # The beta-only term must not leak into alpha.
    for p in ALPHA.rglob("*"):
        if p.is_file():
            try:
                assert "betaonlyterm" not in p.read_text(errors="strict")
            except (UnicodeDecodeError, ValueError):
                pass


def test_gitignored_file_is_really_covered_by_gitignore():
    gitignore = (ALPHA / ".gitignore").read_text()
    assert "ignored_secret.py" in gitignore
    assert "*.log" in gitignore
    assert "ignoredtermxyz" in (ALPHA / "ignored_secret.py").read_text()
    assert "logtermxyz" in (ALPHA / "notes.log").read_text()


def test_binary_fixture_is_binary_and_planted():
    data = (ALPHA / "payload.zip").read_bytes()
    assert b"\x00" in data, "binary fixture contains no NUL byte"
    assert b"binarytermxyz" in data


def test_node_modules_fixture_is_planted():
    text = (ALPHA / "node_modules" / "somelib" / "index.js").read_text()
    assert "nodemoduletermxyz" in text


def test_longline_fixture_line_is_long_and_searchable():
    lines = (ALPHA / "src" / "longline.py").read_text().splitlines()
    longest = max(lines, key=len)
    assert len(longest) > 9000
    assert "needlelongline" in longest


def test_reference_fixture_has_middle_term_with_room_around_it():
    lines = (ALPHA / "src" / "reference.py").read_text().splitlines()
    assert len(lines) >= 55
    hits = [i for i, ln in enumerate(lines) if "middletermreference" in ln]
    assert len(hits) == 1
    assert 10 < hits[0] < len(lines) - 10


def test_utils_fixture_has_original_term_for_incremental_edit():
    assert "utilstermoriginal" in (ALPHA / "src" / "utils.py").read_text()


def test_beta_guide_has_unique_word():
    text = (BETA / "docs" / "guide.md").read_text()
    assert "onboarding" in text
    for p in ALPHA.rglob("*"):
        if p.is_file():
            try:
                assert "onboarding" not in p.read_text(errors="strict")
            except (UnicodeDecodeError, ValueError):
                pass


def test_outside_fixture_has_its_term():
    assert "outsidetermxyz" in (OUTSIDE / "outside.py").read_text()
