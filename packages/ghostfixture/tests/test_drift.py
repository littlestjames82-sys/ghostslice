"""Bundle-vs-project drift reporting (polish round, Oct 14, 2026).

Fixture copies ORIGINALS, so if the project changed after the
bundle was exported the fixture silently held newer bytes; v0.1
only pinned the pairing by the bundle manifest hash. Now, for
bundle entries at mode "full" (where the bundle manifest sha256
is taken over the file itself), the build byte-compares what it
copied against the bundle's recorded sha256 and lists mismatches
under "drift" in the manifest and as a warning in FIXTURE.md.
Other modes store sliced text and must never be claimed either
way.
"""
from __future__ import annotations

import hashlib

import pytest

import helpers

pytestmark = pytest.mark.usefixtures("requires_cli")


def _entry(manifest, path):
    return next(e for e in manifest["included"] if e["path"] == path)


def test_no_drift_on_a_fresh_bundle(repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    assert manifest["drift"] == []
    assert manifest["totals"]["files_drifted"] == 0
    # main.py + config.py are bundle-referenced at full mode and
    # copied; secrets_store.py is excluded-flagged before copying.
    assert manifest["drift_check"]["comparable_files"] == 2
    entry = _entry(manifest, "app/main.py")
    assert entry["matches_bundle_content"] is True
    assert entry["bundle_sha256"] == hashlib.sha256(
        (repro_project / "app/main.py").read_bytes()).hexdigest()
    md = (out / "FIXTURE.md").read_text(encoding="utf-8")
    assert "Drift check:" in md
    assert "match the bundle's recorded content" in md
    assert "## Drift warning" not in md


def test_drift_detected_after_a_project_edit(repro_project, repro_bundle, tmp_path):
    edited = repro_project / "app/main.py"
    edited.write_bytes(edited.read_bytes() + b"\n# changed after export\n")
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    assert [d["path"] for d in manifest["drift"]] == ["app/main.py"]
    assert manifest["totals"]["files_drifted"] == 1
    entry = _entry(manifest, "app/main.py")
    assert entry["matches_bundle_content"] is False
    assert entry["bundle_sha256"] != entry["sha256"]
    # The fixture still holds the CURRENT project bytes, and is
    # internally consistent: check passes on it.
    assert (out / "app/main.py").read_bytes() == edited.read_bytes()
    md = (out / "FIXTURE.md").read_text(encoding="utf-8")
    assert "## Drift warning" in md
    assert "`app/main.py`" in md
    assert "drift warning: 1 copied file(s) differ" in helpers.combined(proc)
    proc = helpers.check_fixture(out)
    assert proc.returncode == 0, helpers.combined(proc)


def test_non_full_mode_is_not_byte_compared(repro_project, tmp_path):
    bundle = helpers.build_bundle(
        repro_project, tmp_path / "mixed_bundle",
        [("app/main.py", "full"), ("app/helper.py", "signatures")])
    edited = repro_project / "app/helper.py"
    edited.write_bytes(edited.read_bytes() + b"\n# changed after export\n")
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    # helper.py is at mode "signatures": the bundle stored sliced
    # text, not the file, so no drift claim is made either way.
    assert manifest["drift"] == []
    entry = _entry(manifest, "app/helper.py")
    assert "matches_bundle_content" not in entry
    assert (out / "app/helper.py").read_bytes() == edited.read_bytes()
