"""Bounded sample pack rules (PLAN.md MVP 2 and verification bar).

- The sample never exceeds the requested bound.
- The manifest states sample size, strategy, and full row counts, and
  the sample file on disk matches the manifest.
- Token estimates carry the estimator method.
"""
from __future__ import annotations

import csv
import io

from conftest import requires_core, run_pack, sample_row_count

BIG_ROWS = 120_000


def _write_big_csv(path, rows=BIG_ROWS):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["n", "label", "grp"])
        for i in range(1, rows + 1):
            writer.writerow([i, "row-%d" % i, i % 3])
    return path


@requires_core
def test_default_sample_is_60_on_a_large_file(tmp_path):
    big = _write_big_csv(tmp_path / "big.csv")
    proc, manifest = run_pack(big, tmp_path / "pack", timeout=300)
    assert manifest["counts"]["rows_total"] == BIG_ROWS
    assert manifest["counts"]["rows_parsed"] == BIG_ROWS
    assert manifest["counts"]["rows_malformed"] == 0
    assert manifest["sample"]["rows"] == 60
    assert manifest["sample"]["size_requested"] == 60
    assert sample_row_count(tmp_path / "pack", manifest) == 60


@requires_core
def test_sample_never_exceeds_the_requested_bound(tmp_path):
    big = _write_big_csv(tmp_path / "big.csv", rows=5_000)
    for bound in (1, 7, 25, 100):
        proc, manifest = run_pack(
            big, tmp_path / ("pack%d" % bound),
            "--sample", bound, timeout=300)
        assert manifest["sample"]["rows"] <= bound
        assert sample_row_count(
            tmp_path / ("pack%d" % bound), manifest) <= bound


@requires_core
def test_sample_bound_above_row_count_gives_all_rows(
        people_csv, tmp_path):
    proc, manifest = run_pack(people_csv, tmp_path / "pack",
                              "--sample", 500)
    assert manifest["sample"]["rows"] == 5
    assert sample_row_count(tmp_path / "pack", manifest) == 5


@requires_core
def test_sample_includes_head_and_tail_rows(tmp_path):
    big = _write_big_csv(tmp_path / "big.csv", rows=3_000)
    proc, manifest = run_pack(big, tmp_path / "pack", timeout=300)
    sample_text = (tmp_path / "pack" / manifest["sample"]["file"]).read_text(
        encoding="utf-8")
    rows = list(csv.reader(io.StringIO(sample_text)))
    labels = [r[1] for r in rows[1:]]
    assert labels[0] == "row-1"          # head
    assert labels[-1] == "row-3000"      # tail
    assert len(labels) == 60
    # a spaced middle row is present, not just head and tail blocks
    assert any(100 < int(lbl.split("-")[1]) < 2900 for lbl in labels)


@requires_core
def test_manifest_states_strategy_counts_and_token_method(
        people_csv, tmp_path):
    proc, manifest = run_pack(people_csv, tmp_path / "pack")
    assert manifest["sample"]["strategy"]  # non-empty statement
    assert manifest["sample"]["strategy_counts"]
    assert manifest["counts"]["rows_total"] == 5
    tokens = manifest["tokens"]
    assert tokens["method"]  # estimator method stamped
    assert tokens["sample_estimate"] > 0
    assert tokens["full_file_estimate"] >= tokens["sample_estimate"]


@requires_core
def test_pack_layout_matches_plan(people_csv, tmp_path):
    proc, manifest = run_pack(people_csv, tmp_path / "pack")
    pack = tmp_path / "pack"
    assert (pack / "manifest.json").is_file()
    assert (pack / "PROMPT.md").is_file()
    assert (pack / manifest["sample"]["file"]).is_file()
    prompt = (pack / "PROMPT.md").read_text(encoding="utf-8")
    assert "people.csv" in prompt
    assert "5" in prompt  # row counts stated in words too
