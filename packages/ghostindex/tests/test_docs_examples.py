"""Documentation and examples contract: the README states the job,
the commands, and the honest limits in plain words, and the examples
folder holds two real fixture projects plus a captured session.
These tests need no core."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
EXAMPLES = ROOT / "examples"


def _readme() -> str:
    assert README.is_file(), "README.md is missing"
    return README.read_text()


def test_readme_states_the_job_and_the_store():
    text = _readme().lower()
    assert "ghostindex" in text
    assert "fts5" in text or "full-text" in text or "full text" in text
    assert "sqlite" in text
    assert "offline" in text
    assert "excerpt" in text


def test_readme_documents_commands_and_exit_codes():
    text = _readme()
    for cmd in ("index", "update", "search", "list", "stats", "remove",
                "doctor"):
        assert f"ghostindex {cmd}" in text or f"`{cmd}`" in text, (
            f"README does not document the {cmd} command")
    assert "--db" in text
    low = text.lower()
    assert "no matches" in low  # exit code 1 meaning is written down


def test_readme_has_no_em_dashes():
    assert "\u2014" not in _readme(), "README contains an em dash"


def test_readme_states_honest_limits():
    low = _readme().lower()
    # Keyword search only: the README must not sell semantic search,
    # and must say what v0.1 ranking is.
    assert "keyword" in low
    assert "semantic" in low  # named so it can be ruled out, plainly
    assert "estimate" in low  # token figures are labelled estimates


def test_readme_names_what_is_not_indexed():
    low = _readme().lower()
    assert ".gitignore" in low
    assert "binary" in low


def test_examples_have_two_projects_with_shared_phrase():
    alpha = EXAMPLES / "project_alpha"
    beta = EXAMPLES / "project_beta"
    assert (alpha / "src" / "greeter.py").is_file()
    assert (beta / "src" / "ledger.py").is_file()
    a_text = (alpha / "src" / "greeter.py").read_text()
    b_text = (beta / "src" / "ledger.py").read_text()
    assert "sunflower festival" in a_text
    assert "sunflower festival" in b_text


def test_examples_alpha_gitignore_covers_scratch_file():
    alpha = EXAMPLES / "project_alpha"
    assert "scratch_notes.py" in (alpha / ".gitignore").read_text()
    assert "scratchterm" in (alpha / "scratch_notes.py").read_text()


def test_sample_search_session_is_captured_and_consistent():
    session = EXAMPLES / "sample_search_session.md"
    assert session.is_file(), "examples/sample_search_session.md missing"
    text = session.read_text()
    assert "greeter.py" in text and "ledger.py" in text
    assert "sunflower festival" in text
    # The ignored file's term must show as a no-match in the session.
    assert "scratchterm" in text
    assert "\u2014" not in text
