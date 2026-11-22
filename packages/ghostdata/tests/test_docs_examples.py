"""Docs and examples contract: README states the limits in plain
words with no em dashes, and the shipped example packs verify."""
from __future__ import annotations

from pathlib import Path

from conftest import ROOT, requires_core, run_cli

EXAMPLES = ROOT / "examples"


def test_readme_exists_and_has_no_em_dashes():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "GhostData" in readme
    assert "—" not in readme  # no em dashes in docs copy
    assert "--no-redact" in readme


def test_readme_states_the_honest_limits():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    for needle in ("inferred", "capped", "luhn", "estimates"):
        assert needle in readme, needle


def test_examples_readme_has_no_em_dashes():
    text = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    assert "—" not in text


@requires_core
def test_example_packs_pass_check():
    for pack in ("customers-pack", "events-pack"):
        proc = run_cli(["check", EXAMPLES / pack])
        assert proc.returncode == 0, (pack, proc.stdout)


def test_example_packs_contain_no_source_secrets():
    for pack in ("customers-pack", "events-pack"):
        for path in Path(EXAMPLES / pack).rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                assert "example.com" not in text, str(path)
                assert "EXAMPLE_ONLY_TOKEN" not in text, str(path)


def test_example_sources_exist():
    assert (EXAMPLES / "customers.csv").is_file()
    assert (EXAMPLES / "events.jsonl").is_file()
    assert (EXAMPLES / "customers-pack" / "manifest.json").is_file()
    assert (EXAMPLES / "events-pack" / "manifest.json").is_file()
