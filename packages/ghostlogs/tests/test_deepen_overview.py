"""Deepen-round pins: the evidence overview (hour buckets plus
severity/pattern match tallies) in manifest.json and INCIDENT.md.

The overview is evidence only: exact counts of what matched, how
often, and in which hour, counted over the whole file. It carries
no line text, changes no kept/collapsed/dropped accounting, and
must stay consistent with itself: bucket line counts sum to the
timestamped-line total, bucket matched counts plus the
no-timestamp matched count sum to the matched-line total, and the
severity tallies sum to the matched-line total.
"""
from conftest import (
    AWS_CANARY,
    CANARY,
    TOTAL_LINES,
    all_output_text,
    build_pack,
    load_manifest,
    pack_text,
)


def _assert_overview_consistent(manifest):
    s = manifest["summary"]
    total = manifest["counts"]["total_lines"]
    assert s["lines_with_timestamp"] + s["lines_without_timestamp"] == total
    buckets = s["timeline"]["list"]
    assert sum(b["lines"] for b in buckets) == s["lines_with_timestamp"]
    assert sum(b["matched_lines"] for b in buckets) \
        + s["matched_lines_without_timestamp"] == s["matched_lines"]
    assert sum(s["by_severity"].values()) == s["matched_lines"]
    assert manifest["counts"]["reconciles"] is True


def test_fixture_overview_matches_ground_truth(log_copy, tmp_path):
    """Hand-counted from tests/fixtures/noisy.log: matched lines are
    the ERROR at 57, the Traceback start at 58, the exception line
    at 61, the ERRORs at 63-66, and the ERROR at 68. Four lines
    carry no timestamp (58-61, the traceback block); two of them
    matched, so they fall in no bucket."""
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    manifest = load_manifest(out)
    s = manifest["summary"]
    assert s["matched_lines"] == 8
    assert s["by_severity"] == {"2": 8}
    assert s["by_pattern"] == {
        "error-level": 6, "exception-name": 1, "traceback-start": 1}
    assert s["lines_with_timestamp"] == 66
    assert s["lines_without_timestamp"] == 4
    assert s["matched_lines_without_timestamp"] == 2
    assert s["timeline"]["buckets"] == 2
    assert s["timeline"]["list"] == [
        {"bucket": "2026-10-14T07:00", "first_line": 1, "last_line": 1,
         "lines": 1, "matched_lines": 0, "max_severity": 0},
        {"bucket": "2026-10-14T08:00", "first_line": 2, "last_line": 70,
         "lines": 65, "matched_lines": 6, "max_severity": 2},
    ]
    _assert_overview_consistent(manifest)
    text = pack_text(out)
    assert "## Evidence overview" in text
    assert "Matched lines: 8 of 70" in text
    assert "2026-10-14T08:00: 65 lines, 6 matched" in text
    assert TOTAL_LINES == 70


def test_overview_severity_and_buckets_on_synthetic_log(tmp_path):
    log = tmp_path / "sev.log"
    log.write_text(
        "2026-10-14T01:00:00Z INFO boot\n"
        "2026-10-14T01:15:00Z FATAL disk gone\n"
        "2026-10-14T02:00:00Z ERROR first failure\n"
        "2026-10-14T02:30:00Z ERROR second failure\n"
        "panic: runtime exploded\n"
        "2026-10-14T03:00:00Z INFO done\n"
    )
    proc, out = build_pack(log, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    s = load_manifest(out)["summary"]
    assert s["matched_lines"] == 4
    assert s["by_severity"] == {"3": 2, "2": 2}
    assert s["by_pattern"] == {
        "fatal-level": 1, "panic": 1, "error-level": 2}
    assert s["lines_with_timestamp"] == 5
    assert s["matched_lines_without_timestamp"] == 1
    by_bucket = {b["bucket"]: b for b in s["timeline"]["list"]}
    assert by_bucket["2026-10-14T01:00"]["matched_lines"] == 1
    assert by_bucket["2026-10-14T01:00"]["max_severity"] == 3
    assert by_bucket["2026-10-14T02:00"]["matched_lines"] == 2
    assert by_bucket["2026-10-14T03:00"]["matched_lines"] == 0
    _assert_overview_consistent(load_manifest(out))


def test_line_matching_two_patterns_counts_once_at_top_severity(tmp_path):
    """A line matching two patterns is one matched line (at the
    highest severity) but appears in both per-pattern tallies, so
    the tallies may sum above the matched-line total. That rule is
    stated in the manifest limits."""
    log = tmp_path / "multi.log"
    log.write_text(
        "2026-10-14T04:00:00Z FATAL panic: core melted\n"
        "2026-10-14T04:01:00Z INFO calm\n"
    )
    proc, out = build_pack(log, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    s = load_manifest(out)["summary"]
    assert s["matched_lines"] == 1
    assert s["by_severity"] == {"3": 1}
    assert s["by_pattern"] == {"fatal-level": 1, "panic": 1}
    _assert_overview_consistent(load_manifest(out))


def test_syslog_timestamps_bucket_without_invented_year(tmp_path):
    log = tmp_path / "syslog.log"
    log.write_text(
        "Oct 14 08:00:01 myhost sshd: started\n"
        "Oct 14 08:10:00 myhost app: ERROR widget failed\n"
        "Oct 14 09:00:00 myhost app: stopped\n"
    )
    proc, out = build_pack(log, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    s = load_manifest(out)["summary"]
    assert s["matched_lines"] == 1
    labels = [b["bucket"] for b in s["timeline"]["list"]]
    assert labels == [
        "Oct 14 08:00 (syslog, no year in source)",
        "Oct 14 09:00 (syslog, no year in source)",
    ]
    assert s["timeline"]["list"][0]["matched_lines"] == 1
    _assert_overview_consistent(load_manifest(out))


def test_log_without_timestamps_has_no_buckets(tmp_path):
    log = tmp_path / "plain.log"
    log.write_text(
        "INFO starting\n"
        "ERROR plain failure with no time\n"
        "INFO ending\n"
    )
    proc, out = build_pack(log, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    manifest = load_manifest(out)
    s = manifest["summary"]
    assert s["matched_lines"] == 1
    assert s["lines_with_timestamp"] == 0
    assert s["timeline"]["buckets"] == 0
    assert s["matched_lines_without_timestamp"] == 1
    assert "No recognised timestamps, so no hour buckets" in pack_text(out)
    _assert_overview_consistent(manifest)


def test_custom_cli_pattern_is_counted_in_overview(tmp_path):
    log = tmp_path / "widget.log"
    log.write_text(
        "2026-10-14T05:00:00Z INFO widget spun up\n"
        "2026-10-14T05:01:00Z INFO widget spun down\n"
    )
    proc, out = build_pack(log, tmp_path / "pack", ["--pattern", "widget"])
    assert proc.returncode == 0, proc.stderr
    s = load_manifest(out)["summary"]
    assert s["matched_lines"] == 2
    assert s["by_pattern"] == {"cli-1": 2}
    assert s["by_severity"] == {"2": 2}
    _assert_overview_consistent(load_manifest(out))


def test_overview_carries_no_secret_shaped_values(tmp_path):
    """The overview is counts and timestamp prefixes only: planted
    secret shapes on matched and routine lines appear nowhere in
    any output, while the matched line is still counted."""
    log = tmp_path / "secret.log"
    log.write_text(
        "2026-10-14T06:00:00Z INFO boot\n"
        f"2026-10-14T06:01:00Z ERROR auth failed for key {AWS_CANARY}\n"
        f"2026-10-14T06:02:00Z INFO token {CANARY} seen\n"
        "2026-10-14T06:03:00Z INFO done\n"
    )
    proc, out = build_pack(log, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    everything = all_output_text(out, proc)
    assert AWS_CANARY not in everything
    assert CANARY not in everything
    s = load_manifest(out)["summary"]
    assert s["matched_lines"] == 1
    assert s["by_pattern"] == {"error-level": 1}


def test_anchors_tier_compacts_overview_but_manifest_keeps_it(log_copy,
                                                             tmp_path):
    """At the anchors tier the pack face carries the counts alone
    (buckets and tallies live in the manifest), so the summary
    cannot crowd out the mandatory anchors; the budget-600 fit the
    suite pins still lands."""
    proc, out = build_pack(log_copy, tmp_path / "pack", ["--budget", "600"])
    assert proc.returncode == 0, proc.stderr
    manifest = load_manifest(out)
    assert manifest["budget_tier"] == "anchors"
    assert manifest["summary"]["timeline"]["buckets"] == 2
    text = pack_text(out)
    assert "## Evidence overview" in text
    assert "tallies are in manifest.json" in text
    _assert_overview_consistent(manifest)
