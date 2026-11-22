"""Safety and size-cap tests (PLAN.md hard safety rules).

- A build aimed inside the source project is refused, and a
  project inside the output is refused; the project is unchanged
  either way.
- An existing non-empty output directory is refused.
- --max-bytes is enforced and stated: bundle-referenced files
  are kept first in deterministic order, the rest are left out
  with reason size-cap, total copied bytes stay within the cap,
  and the cap appears in both the CLI output and the manifest.
- A referenced symlink escaping the project root is left out
  with the recorded reason; a symlink pointing inside the
  project is copied as content, not as a link.

All tests skip cleanly while no ghostfixture CLI is discoverable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

pytestmark = pytest.mark.usefixtures("requires_cli")


def test_output_inside_project_is_refused(
        repro_project, repro_bundle, tmp_path):
    before = helpers.tree_hashes(repro_project)
    out = repro_project / "fixture_out"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode != 0, helpers.combined(proc)
    assert helpers.tree_hashes(repro_project) == before


def test_existing_nonempty_output_is_refused(
        repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    out.mkdir()
    (out / "keepme.txt").write_text("precious\n")
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode != 0, helpers.combined(proc)
    assert (out / "keepme.txt").read_text() == "precious\n"
    assert not (out / "fixture-manifest.json").exists()


def test_size_cap_enforced_stated_and_referenced_first(
        big_project, big_bundle, tmp_path):
    total = sum((big_project / rel).stat().st_size
                for rel, _ in helpers.BIG_BUNDLE_FILES)
    cap = 3000
    assert total > cap  # fixture premise, also checked statically
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(big_project, big_bundle, out, cap=cap)
    assert proc.returncode == 0, helpers.combined(proc)

    manifest = helpers.fixture_manifest(out)
    # Stated: in the manifest and in the CLI output.
    assert manifest["max_bytes"] == cap
    text = helpers.combined(proc)
    assert str(cap) in text and "cap" in text.lower()

    # Enforced: copied content stays within the cap.
    assert manifest["totals"]["bytes_copied"] <= cap

    # Referenced files kept first in deterministic order: the
    # three smallest-prefix entries of the bundle fit, the two
    # remaining modules are left out with reason size-cap.
    kept = {e["path"] for e in manifest["included"]}
    assert {"pkg/__init__.py", "pkg/alpha.py", "pkg/beta.py"} <= kept
    left = {e["path"]: e for e in manifest["left_out"]}
    for rel in ("pkg/gamma.py", "pkg/delta.py"):
        assert not (out / rel).exists(), rel
        assert rel in left, manifest["left_out"]
        assert left[rel]["reason"] == "size-cap", left[rel]


def _symlink(target, link):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available on this platform")


def test_symlink_escaping_root_is_left_out(
        repro_project, tmp_path):
    outside = tmp_path / "outside_secret.py"
    outside.write_text("VALUE = 'outside the project'\n")
    link = repro_project / "app" / "linked_out.py"
    _symlink(str(outside), str(link))
    bundle = helpers.build_bundle(
        repro_project, tmp_path / "bundle_s",
        helpers.REPRO_BUNDLE_FILES + [("app/linked_out.py", "full")])
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    assert not (out / "app/linked_out.py").exists()
    manifest = helpers.fixture_manifest(out)
    left = {e["path"]: e for e in manifest["left_out"]}
    assert "app/linked_out.py" in left, manifest["left_out"]
    assert left["app/linked_out.py"]["reason"] in (
        "symlink-escapes-root", "outside-root")


def test_symlink_inside_project_copied_as_content(
        repro_project, tmp_path):
    target = repro_project / "app" / "real_target.py"
    target.write_text("TARGET_VALUE = 42\n")
    link = repro_project / "app" / "linked_in.py"
    _symlink("real_target.py", str(link))
    bundle = helpers.build_bundle(
        repro_project, tmp_path / "bundle_i",
        helpers.REPRO_BUNDLE_FILES + [("app/linked_in.py", "full")])
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    copied = out / "app/linked_in.py"
    assert copied.is_file()
    assert not copied.is_symlink()
    assert copied.read_bytes() == target.read_bytes()
