"""Verification bar #3 (PLAN.md): exporting a fixture with a planted
secret-shaped literal produces a bundle with ZERO occurrences of that
literal on the default path, plus a manifest redaction record.
The source project must not be altered: transforms happen in the
exported copy only."""
from __future__ import annotations

from pathlib import Path

from conftest import FAKE_SECRET, copy_fixture
from helpers import read_all_text


def _export(cli, project, pack, out):
    result = cli(["export", project, "--surface", pack, "-o", out])
    assert result.returncode == 0, f"export failed:\n{result.stdout}\n{result.stderr}"
    return out


def test_planted_secret_never_ships_by_default(cli, surface_pack, tmp_path):
    project = copy_fixture("planted_key_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    texts = read_all_text(bundle)
    offenders = [rel for rel, text in texts.items() if FAKE_SECRET in text]
    assert offenders == [], f"planted fake secret shipped in: {offenders}"


def test_redaction_is_recorded(cli, surface_pack, tmp_path):
    project = copy_fixture("planted_key_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    texts = read_all_text(bundle)
    evidence = [
        rel for rel, text in texts.items()
        if rel in ("exposure.json", "manifest.json") and "redact" in text.lower()
    ]
    assert evidence, "no redaction record found in exposure.json or manifest.json"
    joined = " ".join(texts[rel] for rel in evidence)
    assert "secrets_config.py" in joined, "redaction record must name the file it redacted"


def test_source_project_is_not_altered(cli, surface_pack, tmp_path):
    project = copy_fixture("planted_key_project", tmp_path)
    source_file = project / "config" / "secrets_config.py"
    before = source_file.read_text()
    _export(cli, project, surface_pack, tmp_path / "bundle")
    assert source_file.read_text() == before
    assert FAKE_SECRET in before, "fixture source keeps the fake secret: only the export is redacted"
