"""Source immutability and pack checking (PLAN.md: "Source files are
never modified"; MVP 4 pack check)."""
from __future__ import annotations

import shutil
from pathlib import Path

from conftest import (FIXTURES, requires_core, run_cli, run_pack,
                      sha256_of)

DATA_FILES = ["people.csv", "orders.csv", "events.jsonl",
              "records.json", "temps.tsv"]


@requires_core
def test_source_byte_identical_after_schema_and_pack(tmp_path):
    for name in DATA_FILES:
        src = tmp_path / name
        shutil.copy(FIXTURES / name, src)
        before = sha256_of(src)
        proc = run_cli(["schema", src])
        assert proc.returncode == 0, proc.stderr
        run_pack(src, tmp_path / ("pack-" + name))
        assert sha256_of(src) == before, name
        # the manifest records the same source hash we computed
        import json
        manifest = json.loads(
            (tmp_path / ("pack-" + name) / "manifest.json").read_text())
        assert manifest["source"]["sha256"] == before


@requires_core
def test_check_passes_on_a_fresh_pack(people_csv, tmp_path):
    run_pack(people_csv, tmp_path / "pack")
    proc = run_cli(["check", tmp_path / "pack"])
    assert proc.returncode == 0, proc.stdout + proc.stderr


@requires_core
def test_check_fails_on_a_tampered_sample(people_csv, tmp_path):
    proc0, manifest = run_pack(people_csv, tmp_path / "pack")
    sample = tmp_path / "pack" / manifest["sample"]["file"]
    text = sample.read_text(encoding="utf-8")
    sample.write_text(text + "\n", encoding="utf-8")
    proc = run_cli(["check", tmp_path / "pack"])
    assert proc.returncode == 1, proc.stdout


@requires_core
def test_check_fails_on_a_missing_pack(tmp_path):
    proc = run_cli(["check", tmp_path / "nope"])
    assert proc.returncode == 1


@requires_core
def test_missing_source_file_is_an_error_not_a_crash(tmp_path):
    proc = run_cli(["schema", tmp_path / "absent.csv"])
    assert proc.returncode == 2
    assert "absent.csv" in proc.stderr


@requires_core
def test_empty_file_is_an_error_not_a_crash(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    proc = run_cli(["schema", empty])
    assert proc.returncode == 2
