"""Fixture sanity: the hand-computed expectations in the other test
files rest on these raw facts, verified here with the stdlib alone so
a broken fixture cannot masquerade as a broken core."""
from __future__ import annotations

import csv
import json

from conftest import FIXTURES


def test_people_csv_raw_shape():
    with open(FIXTURES / "people.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["id", "name", "age", "score", "active", "joined",
                       "email", "password_hash", "contact", "payment",
                       "ref"]
    assert len(rows) == 6  # header + 5 data rows
    assert all(len(r) == 11 for r in rows)


def test_orders_csv_ragged_rows_are_where_tests_expect():
    with open(FIXTURES / "orders.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    assert len(rows[0]) == 4
    # file line numbers (1-indexed): line 3 short, line 4 long
    assert len(rows[2]) == 3
    assert len(rows[3]) == 5


def test_events_jsonl_line_3_is_invalid_json():
    lines = (FIXTURES / "events.jsonl").read_text().splitlines()
    assert len(lines) == 4
    for i, line in enumerate(lines):
        if i == 2:
            try:
                json.loads(line)
                raise AssertionError("line 3 should not parse")
            except json.JSONDecodeError:
                pass
        else:
            assert isinstance(json.loads(line), dict)


def test_records_json_is_a_three_object_array():
    data = json.loads((FIXTURES / "records.json").read_text())
    assert isinstance(data, list) and len(data) == 3
    assert all(isinstance(item, dict) for item in data)


def test_temps_tsv_raw_shape():
    lines = (FIXTURES / "temps.tsv").read_text().splitlines()
    assert lines[0].split("\t") == ["station", "reading", "unit"]
    assert len(lines) == 4
