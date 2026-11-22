"""Polish-round regression tests: every number inspect and the artifact
headers print must be exact, including when the manifest omits data.

These pin wording fixes, not new behavior:
- the inspect census line used to label the included (non-excluded)
  count as "with bodies", counting bodyless entries as bodies;
- the inspect totals line printed "None sliced of None original" when
  the manifest recorded no totals;
- artifact headers printed "saved None" when the manifest recorded
  totals but no total_saved_tokens.
"""
from __future__ import annotations

from pathlib import Path

from conftest import combined, entry, run_gc, write_hand_bundle

EMPTY_SHA256 = ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


def _files_line(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("Files:"):
            return line
    raise AssertionError(f"no Files: line in inspect output:\n{stdout}")


def test_inspect_census_counts_sum_to_the_total(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[
            entry("src/a.py", "full", sliced_tokens=10, sha256="a" * 64),
            entry("tests/t.py", "strip-tests", sliced_tokens=0,
                  sha256=EMPTY_SHA256),
            entry("src/lost.py", "full", sliced_tokens=25, sha256="b" * 64),
            entry("vendor/v.py", "exclude"),
        ],
        bodies={"src/a.py": "x = 1\n"})
    proc = run_gc("inspect", str(bundle))
    assert proc.returncode == 0, combined(proc)
    # 4 = 1 with a body + 1 emptied by Slice + 1 genuinely missing + 1
    # excluded. The pre-polish line claimed "3 with bodies".
    assert _files_line(proc.stdout) == (
        "Files: 4 (1 with bodies, 1 emptied by GhostSlice, "
        "1 missing bodies, 1 excluded)")


def test_inspect_census_common_case_stays_short(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[
            entry("src/a.py", "full", sliced_tokens=10, sha256="a" * 64),
            entry("vendor/v.py", "exclude"),
        ],
        bodies={"src/a.py": "x = 1\n"})
    proc = run_gc("inspect", str(bundle))
    assert proc.returncode == 0, combined(proc)
    assert _files_line(proc.stdout) == "Files: 2 (1 with bodies, 1 excluded)"


def test_inspect_totals_not_recorded_is_named_not_none(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("src/a.py", "full", sliced_tokens=10,
                       sha256="a" * 64)],
        bodies={"src/a.py": "x = 1\n"},
        extra_manifest={"total_sliced_tokens": None,
                        "total_original_tokens": None})
    proc = run_gc("inspect", str(bundle))
    assert proc.returncode == 0, combined(proc)
    assert "Totals: not recorded in the manifest" in proc.stdout
    assert "None sliced" not in proc.stdout


def test_artifact_header_omits_saved_when_manifest_lacks_it(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("src/a.py", "full", sliced_tokens=10,
                       sha256="a" * 64)],
        bodies={"src/a.py": "x = 1\n"},
        extra_manifest={"total_saved_tokens": None})
    out = tmp_path / "out"
    proc = run_gc("convert", str(bundle), "--to", "agents", "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    text = (out / "AGENTS.md").read_text(encoding="utf-8")
    assert "saved None" not in text
    assert "Estimated tokens: 90 sliced (was 100)." in text


def test_artifact_header_keeps_saved_when_manifest_records_it(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("src/a.py", "full", sliced_tokens=10,
                       sha256="a" * 64)],
        bodies={"src/a.py": "x = 1\n"})
    out = tmp_path / "out"
    proc = run_gc("convert", str(bundle), "--to", "generic", "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    text = (out / "prompt.md").read_text(encoding="utf-8")
    assert "Estimated tokens: 90 sliced (was 100, saved 10)." in text
