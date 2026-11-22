"""Show command (PLAN MVP item 2): `ghosthandoff show <pack-dir>`
prints HANDOFF.md."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

import helpers  # noqa: E402

pytestmark = pytest.mark.skipif(
    not helpers.cli_available(),
    reason="ghosthandoff CLI not discoverable (see REPORT_B.md)")


def test_show_prints_the_pack(fixture_repo, tmp_path):
    outdir = tmp_path / "pack-out"
    proc = helpers.run_cli(
        ["pack", str(fixture_repo), "-o", str(outdir)], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    shown = helpers.run_cli(["show", str(outdir)], cwd=tmp_path)
    assert shown.returncode == 0, shown.stderr
    on_disk = helpers.pack_text(outdir)
    assert shown.stdout.strip() == on_disk.strip()
    assert helpers.BRANCH in shown.stdout
