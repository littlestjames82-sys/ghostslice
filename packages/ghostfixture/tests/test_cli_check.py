"""Check round-trip tests (PLAN.md MVP item 4).

- ``ghostfixture check`` on a freshly built fixture exits 0.
- Editing a copied file afterwards makes it exit 1.
- Adding an unexplained extra file makes it exit 1.
- Restoring a file's original bytes makes it pass again, and a
  directory that is not a fixture exits 2 (could not check).
- The excluded secret-flagged file must never be present; if
  one is planted into the tree by hand, check must fail.

All tests skip cleanly while no ghostfixture CLI is discoverable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

pytestmark = pytest.mark.usefixtures("requires_cli")


@pytest.fixture()
def built(repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    return out


def test_check_passes_on_fresh_fixture(built):
    proc = helpers.check_fixture(built)
    assert proc.returncode == 0, helpers.combined(proc)


def test_check_fails_after_a_copied_file_is_edited(built):
    target = built / "app/config.py"
    target.write_text(target.read_text() + "# tampered\n")
    proc = helpers.check_fixture(built)
    assert proc.returncode == 1, helpers.combined(proc)


def test_check_passes_again_after_restore(built, repro_project):
    target = built / "app/config.py"
    original = target.read_bytes()
    target.write_bytes(original + b"# tampered\n")
    assert helpers.check_fixture(built).returncode == 1
    target.write_bytes(original)
    proc = helpers.check_fixture(built)
    assert proc.returncode == 0, helpers.combined(proc)


def test_check_fails_on_unexplained_extra_file(built):
    (built / "app" / "smuggled.py").write_text("X = 1\n")
    proc = helpers.check_fixture(built)
    assert proc.returncode == 1, helpers.combined(proc)


def test_check_fails_if_flagged_file_is_planted(built, repro_project):
    planted = built / helpers.SECRET_FILE
    planted.write_bytes((repro_project / helpers.SECRET_FILE).read_bytes())
    proc = helpers.check_fixture(built)
    assert proc.returncode == 1, helpers.combined(proc)


def test_check_on_missing_directory_exits_2(tmp_path):
    proc = helpers.check_fixture(tmp_path / "no_such_fixture")
    assert proc.returncode == 2, helpers.combined(proc)
