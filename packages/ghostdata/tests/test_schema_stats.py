"""Schema stats against hand-computed fixture values (PLAN.md MVP 1).

All expectations below were computed by hand from the fixture files
in tests/fixtures/, not from the tool's own output.
"""
from __future__ import annotations

from conftest import column, requires_core, run_schema


@requires_core
def test_people_csv_stats(people_csv):
    out = run_schema(people_csv)
    assert out["format"] == "csv"
    assert out["counts"]["rows_parsed"] == 5
    assert out["counts"]["rows_malformed"] == 0
    assert out["counts"]["rows_total"] == 5

    col = column(out, "id")
    assert col["type"] == "integer"
    assert col["null_count"] == 0
    assert col["distinct_count"] == 5
    assert col["min"] == 1 and col["max"] == 5

    col = column(out, "name")
    assert col["type"] == "string"
    assert col["distinct_count"] == 5
    assert col["min_length"] == 3 and col["max_length"] == 5

    col = column(out, "age")
    assert col["type"] == "integer"
    assert col["null_count"] == 1
    assert col["null_rate"] == 0.2
    assert col["distinct_count"] == 4
    assert col["min"] == 25 and col["max"] == 41

    col = column(out, "score")
    assert col["type"] == "float"
    assert col["null_count"] == 1
    assert col["distinct_count"] == 4
    assert col["min"] == 77.25 and col["max"] == 100.0

    col = column(out, "active")
    assert col["type"] == "boolean"
    assert col["null_count"] == 0
    assert col["distinct_count"] == 2

    col = column(out, "joined")
    assert col["type"] == "date"
    assert col["null_count"] == 1
    assert col["distinct_count"] == 4


@requires_core
def test_events_jsonl_stats(events_jsonl):
    out = run_schema(events_jsonl)
    assert out["format"] == "jsonl"

    col = column(out, "ts")
    assert col["type"] == "date"
    assert col["distinct_count"] == 3

    col = column(out, "user")
    assert col["type"] == "string"
    assert col["distinct_count"] == 3
    assert col["min_length"] == 2 and col["max_length"] == 2

    col = column(out, "value")
    assert col["type"] == "integer"
    assert col["min"] == 10 and col["max"] == 30
    assert col["distinct_count"] == 3


@requires_core
def test_records_json_stats(records_json):
    out = run_schema(records_json)
    assert out["format"] == "json"
    assert out["counts"]["rows_parsed"] == 3
    assert out["counts"]["rows_malformed"] == 0

    col = column(out, "sku")
    assert col["type"] == "string"
    assert col["distinct_count"] == 3

    col = column(out, "price")
    assert col["type"] == "float"
    assert col["null_count"] == 1
    assert col["min"] == 3.5 and col["max"] == 7.0

    col = column(out, "in_stock")
    assert col["type"] == "boolean"
    assert col["distinct_count"] == 2

    col = column(out, "tags")
    assert col["type"] == "array"


@requires_core
def test_temps_tsv_stats(temps_tsv):
    out = run_schema(temps_tsv)
    assert out["format"] == "tsv"
    assert out["counts"]["rows_parsed"] == 3

    col = column(out, "station")
    assert col["type"] == "string"
    assert col["distinct_count"] == 3
    assert col["min_length"] == 4 and col["max_length"] == 5

    col = column(out, "reading")
    assert col["type"] == "float"
    assert col["min"] == -3.25 and col["max"] == 19.0
    assert col["distinct_count"] == 3

    col = column(out, "unit")
    assert col["type"] == "string"
    assert col["distinct_count"] == 1
