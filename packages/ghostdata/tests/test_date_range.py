"""Date range tests: earliest and latest values for date columns.

Before this capability, a column that inferred as a date reported no
range at all, while numeric columns reported min/max and string
columns reported length ranges. Expectations below are computed by
hand. The range must be chronological, not lexicographic; it must be
suppressed for redacted columns and for columns whose range claim
would be partial or misleading; and it must stay bounded and exact
on large files (true row count, O(1) extra state).
"""
from __future__ import annotations

from pathlib import Path

from conftest import column, requires_core, run_pack, run_schema


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@requires_core
def test_people_csv_joined_date_range(people_csv):
    out = run_schema(people_csv)
    col = column(out, "joined")
    assert col["type"] == "date"
    # Non-null dates: 2024-01-15, 2024-02-20, 2024-03-05, 2024-05-30.
    # The null row contributes nothing to the range.
    assert col["min"] == "2024-01-15"
    assert col["max"] == "2024-05-30"


@requires_core
def test_events_jsonl_timestamp_range(events_jsonl):
    out = run_schema(events_jsonl)
    col = column(out, "ts")
    assert col["type"] == "date"
    assert col["min"] == "2026-01-01T10:00:00"
    assert col["max"] == "2026-01-01T10:03:00"


@requires_core
def test_range_is_chronological_not_lexicographic(tmp_path):
    # 05:00 at +05:00 is 00:00 UTC, which is earlier than 01:00 UTC,
    # even though its text sorts later than both other spellings.
    path = _write(
        tmp_path, "zones.csv",
        "stamp\n"
        "2024-01-01T05:00:00+05:00\n"
        "2024-01-01T01:00:00Z\n"
        "2024-01-01T03:00:00\n")
    col = column(run_schema(path), "stamp")
    assert col["type"] == "date"
    assert col["min"] == "2024-01-01T05:00:00+05:00"
    assert col["max"] == "2024-01-01T03:00:00"


@requires_core
def test_offset_without_colon_and_space_separator(tmp_path):
    path = _write(
        tmp_path, "forms.csv",
        "stamp\n"
        "2024-06-01 12:00:00+0000\n"
        "2024-06-01T09:30:00\n")
    col = column(run_schema(path), "stamp")
    assert col["min"] == "2024-06-01T09:30:00"
    assert col["max"] == "2024-06-01 12:00:00+0000"


@requires_core
def test_date_only_sorts_at_start_of_day(tmp_path):
    path = _write(
        tmp_path, "mixed_precision.csv",
        "stamp\n2024-01-02\n2024-01-01T23:00:00\n")
    col = column(run_schema(path), "stamp")
    assert col["min"] == "2024-01-01T23:00:00"
    assert col["max"] == "2024-01-02"


@requires_core
def test_unparseable_date_shape_suppresses_range(tmp_path):
    # 2024-13-45 matches the date shape but is not a real calendar
    # date. Reporting a range over the remaining values would present
    # a partial range as whole, so no range is reported.
    path = _write(
        tmp_path, "bad.csv",
        "stamp\n2024-01-15\n2024-13-45\n2024-03-01\n")
    col = column(run_schema(path), "stamp")
    assert col["type"] == "date"
    assert col.get("min") is None and col.get("max") is None


@requires_core
def test_mixed_column_reports_no_date_range(tmp_path):
    path = _write(
        tmp_path, "mixed.csv",
        "stamp\n2024-01-15\nnot-a-date\n2024-03-01\n")
    col = column(run_schema(path), "stamp")
    assert col["type"] == "mixed"
    assert col.get("min") is None and col.get("max") is None


@requires_core
def test_redacted_date_column_suppresses_range(tmp_path):
    # The column name matches the token pattern, so the column is
    # redacted and its range is suppressed like a numeric range.
    path = _write(
        tmp_path, "secret_dates.csv",
        "id,token_expiry\n1,2024-01-15\n2,2025-12-31\n")
    out = run_schema(path)
    col = column(out, "token_expiry")
    assert col["redacted"] is True
    assert col["min"] is None and col["max"] is None
    assert {"name": "token_expiry",
            "reason": col["redaction_reason"]} in out["redacted_columns"]


@requires_core
def test_no_redact_flag_still_reports_range(tmp_path):
    path = _write(
        tmp_path, "secret_dates.csv",
        "id,token_expiry\n1,2024-01-15\n2,2025-12-31\n")
    col = column(run_schema(path, "--no-redact"), "token_expiry")
    assert col["redacted"] is False
    assert col["min"] == "2024-01-15"
    assert col["max"] == "2025-12-31"


@requires_core
def test_pack_manifest_and_prompt_carry_the_range(people_csv, tmp_path):
    proc, manifest = run_pack(people_csv, tmp_path / "pack")
    col = column(manifest, "joined")
    assert col["min"] == "2024-01-15"
    assert col["max"] == "2024-05-30"
    prompt = Path(tmp_path / "pack" / "PROMPT.md").read_text(
        encoding="utf-8")
    assert "min 2024-01-15, max 2024-05-30" in prompt


@requires_core
def test_date_range_stays_exact_on_a_large_file(tmp_path):
    # 20,000 rows in strictly descending order: the range endpoints
    # are the last and first rows respectively, and the parsed row
    # count must remain the true count.
    lines = ["stamp,value"]
    for i in range(20000):
        day = 1 + (i % 28)
        month = 1 + (i % 12)
        year = 2020 + (i % 5)
        lines.append("%04d-%02d-%02d,%d" % (year, month, day, i))
    path = _write(tmp_path, "large.csv", "\n".join(lines) + "\n")
    out = run_schema(path)
    assert out["counts"]["rows_parsed"] == 20000
    assert out["counts"]["rows_total"] == 20000
    col = column(out, "stamp")
    assert col["type"] == "date"
    # Hand-derived extremes of the generated grid: earliest year,
    # month and day coincide at i values covering 2020-01-01, and the
    # latest is 2024-12-28.
    assert col["min"] == "2020-01-01"
    assert col["max"] == "2024-12-28"
