"""Top-level JSON object support (seam fix, Oct 14, 2026).

The ecosystem pass (ghostslice-companions/ECOSYSTEM.md, seam 6) found
that config-shaped JSON, a top-level object, was refused with "top
level is not a json array", leaving the most common JSON shape in
real projects with no slicer. These tests pin the fix:

- An object is one record: its keys are the schema, the sample is
  the object itself (redacted, structurally bounded, truncation
  stated in the manifest).
- Redaction applies at every depth, by key name and by value shape,
  exactly as the column rules do at the top level.
- A top-level scalar stays refused, by name, and an oversize object
  is refused by the stated full-parse guard.

The card literals are the public Visa/Mastercard test numbers; the
token literal contains the conftest CANARY_TOKEN marker. None is a
real credential.
"""
from __future__ import annotations

import json

from conftest import (assert_no_canaries_in_tree, column, requires_core,
                      run_cli, run_pack, run_schema, sha256_of)

CARD = "4111111111111111"          # Luhn-valid public test number
CARD_INT = 4111111111111111
TOKEN = "CANARY_TOKEN_x7f9"

CONFIG = {
    "name": "svc",
    "port": 8080,
    "debug": True,
    "ratio": 0.5,
    "missing": None,
    "server": {"host": "db.local", "port": 5432},
    "tags": ["a", "b"],
}


def _write(tmp_path, name, payload):
    path = tmp_path / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sample_obj(pack_dir, manifest):
    text = (pack_dir / manifest["sample"]["file"]).read_text(
        encoding="utf-8")
    return json.loads(text)


@requires_core
def test_object_schema_types_structure_and_counts(tmp_path):
    path = _write(tmp_path, "config.json", CONFIG)
    out = run_schema(path)
    assert out["format"] == "json-object"
    assert out["counts"]["rows_parsed"] == 1
    assert out["counts"]["rows_total"] == 1
    assert out["counts"]["rows_malformed"] == 0
    assert column(out, "name")["type"] == "string"
    port = column(out, "port")
    assert port["type"] == "integer" and port["min"] == 8080
    assert port["max"] == 8080
    assert column(out, "debug")["type"] == "boolean"
    assert column(out, "ratio")["type"] == "float"
    missing = column(out, "missing")
    assert missing["type"] == "null" and missing["null_count"] == 1
    assert missing["null_rate"] == 1.0
    # nested values are typed, never flattened: same rule as arrays
    assert column(out, "server")["type"] == "object"
    assert column(out, "tags")["type"] == "array"
    assert out["structure"] == {
        "top_level_keys": 7, "total_keys": 9, "max_depth": 2}


@requires_core
def test_object_pack_checks_and_source_unchanged(tmp_path):
    path = _write(tmp_path, "config.json", CONFIG)
    before = sha256_of(path)
    proc, manifest = run_pack(path, tmp_path / "pack")
    assert manifest["source"]["format"] == "json-object"
    assert manifest["sample"]["rows"] == 1
    assert manifest["sample"]["truncated"] is False
    assert "whole object" in manifest["sample"]["strategy"]
    sample = _sample_obj(tmp_path / "pack", manifest)
    assert sample["server"] == {"host": "db.local", "port": 5432}
    assert sample["tags"] == ["a", "b"]
    proc = run_cli(["check", tmp_path / "pack"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sha256_of(path) == before


@requires_core
def test_object_top_level_sensitive_key_redacted(tmp_path):
    path = _write(tmp_path, "svc.json",
                  {"api_token": TOKEN, "name": "svc"})
    proc, manifest = run_pack(path, tmp_path / "pack")
    assert_no_canaries_in_tree(
        tmp_path / "pack", extra_texts=[proc.stdout, proc.stderr])
    recorded = {c["name"] for c in manifest["redaction"]["columns"]}
    assert recorded == {"api_token"}
    sample = _sample_obj(tmp_path / "pack", manifest)
    assert sample["api_token"] == "[REDACTED]"
    assert sample["name"] == "svc"


@requires_core
def test_object_nested_card_shape_redacted(tmp_path):
    path = _write(tmp_path, "pay.json",
                  {"payment": {"ref": CARD, "last4": "1111"}})
    proc, manifest = run_pack(path, tmp_path / "pack")
    assert_no_canaries_in_tree(
        tmp_path / "pack", extra_texts=[proc.stdout, proc.stderr])
    nested = {c["name"]: c["reason"]
              for c in manifest["redaction"]["nested"]}
    assert "payment.ref" in nested
    assert "card" in nested["payment.ref"]
    sample = _sample_obj(tmp_path / "pack", manifest)
    assert sample["payment"]["ref"] == "[REDACTED]"
    # control: a short fragment is not a card shape and stays visible
    assert sample["payment"]["last4"] == "1111"


@requires_core
def test_object_nested_native_int_card_redacted(tmp_path):
    path = _write(tmp_path, "bill.json", {"billing": {"acct": CARD_INT}})
    proc, manifest = run_pack(path, tmp_path / "pack")
    assert_no_canaries_in_tree(
        tmp_path / "pack", extra_texts=[proc.stdout, proc.stderr])
    nested = {c["name"] for c in manifest["redaction"]["nested"]}
    assert nested == {"billing.acct"}
    sample = _sample_obj(tmp_path / "pack", manifest)
    assert sample["billing"]["acct"] == "[REDACTED]"


@requires_core
def test_object_nested_password_key_redacted(tmp_path):
    path = _write(tmp_path, "db.json",
                  {"database": {"host": "db.local",
                                "password": "hunter2-planted"}})
    proc, manifest = run_pack(path, tmp_path / "pack")
    for f in (tmp_path / "pack").rglob("*"):
        if f.is_file():
            assert "hunter2-planted" not in f.read_text(
                encoding="utf-8", errors="replace"), str(f)
    assert "hunter2-planted" not in proc.stdout + proc.stderr
    nested = {c["name"]: c["reason"]
              for c in manifest["redaction"]["nested"]}
    assert "database.password" in nested
    assert "password" in nested["database.password"]
    sample = _sample_obj(tmp_path / "pack", manifest)
    assert sample["database"]["password"] == "[REDACTED]"
    assert sample["database"]["host"] == "db.local"


@requires_core
def test_object_card_value_under_innocuous_key_redacted(tmp_path):
    # One value, one check, one hit: the shape rule for a 1-of-1
    # column (same rule the array/JSONL paths use), and min/max must
    # not print the card number as the column range.
    path = _write(tmp_path, "ref.json", {"ref": CARD})
    proc, manifest = run_pack(path, tmp_path / "pack")
    assert_no_canaries_in_tree(
        tmp_path / "pack", extra_texts=[proc.stdout, proc.stderr])
    col = column(manifest, "ref")
    assert col["redacted"] is True
    assert "card" in col["redaction_reason"]
    assert col["min"] is None and col["max"] is None


@requires_core
def test_object_leading_zero_strings_stay_strings(tmp_path):
    path = _write(tmp_path, "codes.json",
                  {"zip": "00501", "codes": ["01234", "10001"]})
    out = run_schema(path)
    col = column(out, "zip")
    assert col["type"] == "string"
    assert col.get("min") is None
    proc, manifest = run_pack(path, tmp_path / "pack")
    sample = _sample_obj(tmp_path / "pack", manifest)
    assert sample["zip"] == "00501"
    assert sample["codes"] == ["01234", "10001"]


@requires_core
def test_object_deep_nesting_truncation_is_stated(tmp_path):
    deep = {"top": "kept"}
    cur = deep
    for _ in range(9):
        cur["level"] = {}
        cur = cur["level"]
    cur["leaf"] = "bottom"
    path = _write(tmp_path, "deep.json", deep)
    proc, manifest = run_pack(path, tmp_path / "pack")
    assert manifest["sample"]["truncated"] is True
    truncation = manifest["sample"]["truncation"]
    assert truncation["depth_truncations"] >= 1
    assert any("depth" in d for d in truncation["details"])
    sample_text = (tmp_path / "pack" / manifest["sample"]["file"]
                   ).read_text(encoding="utf-8")
    assert "[TRUNCATED]" in sample_text
    assert "bottom" not in sample_text
    sample = json.loads(sample_text)
    assert sample["top"] == "kept"
    prompt = (tmp_path / "pack" / "PROMPT.md").read_text(
        encoding="utf-8")
    assert "truncation" in prompt.lower()


@requires_core
def test_object_wide_long_and_string_truncation_is_stated(tmp_path):
    payload = {
        "wide": {"k%02d" % i: i for i in range(60)},
        "items": list(range(25)),
        "blob": "x" * 1500,
        "small": 1,
    }
    path = _write(tmp_path, "wide.json", payload)
    proc, manifest = run_pack(path, tmp_path / "pack")
    assert manifest["sample"]["truncated"] is True
    truncation = manifest["sample"]["truncation"]
    assert truncation["keys_dropped"] == 10
    assert truncation["items_dropped"] == 5
    assert truncation["strings_truncated"] == 1
    assert "truncated" in proc.stdout
    sample = _sample_obj(tmp_path / "pack", manifest)
    assert len(sample["wide"]) == 50
    assert len(sample["items"]) == 20
    assert sample["blob"].endswith("[TRUNCATED]")
    assert len(sample["blob"]) == 1000 + len("[TRUNCATED]")
    assert sample["small"] == 1
    # the top level itself is the schema and is never key-capped
    assert set(sample) == {"wide", "items", "blob", "small"}


@requires_core
def test_object_top_level_scalars_are_refused_by_name(tmp_path):
    for text in ("42", '"hello"', "true", "null"):
        path = _write(tmp_path, "scalar.json", text)
        proc = run_cli(["schema", path])
        assert proc.returncode == 2, text
        assert "scalar" in proc.stderr, proc.stderr


@requires_core
def test_object_invalid_empty_and_trailing_are_errors(tmp_path):
    for text in ('{"a": }', "{}", '{"a": 1} {"b": 2}'):
        path = _write(tmp_path, "bad.json", text)
        proc = run_cli(["schema", path])
        assert proc.returncode == 2, (text, proc.stdout, proc.stderr)


@requires_core
def test_object_over_the_parse_guard_is_refused(tmp_path):
    # The guard is stated in the error: objects parse whole, arrays
    # stream, so only the object path carries a size limit.
    path = tmp_path / "big.json"
    path.write_text('{"pad": "' + "x" * 17_000_000 + '"}',
                    encoding="utf-8")
    proc = run_cli(["schema", path])
    assert proc.returncode == 2
    assert "guard" in proc.stderr and "16 MiB" in proc.stderr


@requires_core
def test_object_no_redact_shows_nested_values_and_records_it(tmp_path):
    path = _write(tmp_path, "db.json",
                  {"database": {"password": "hunter2-planted"}})
    proc, manifest = run_pack(path, tmp_path / "pack", "--no-redact")
    assert manifest["redaction"]["enabled"] is False
    assert manifest["redaction"]["columns"] == []
    assert manifest["redaction"]["nested"] == []
    sample = _sample_obj(tmp_path / "pack", manifest)
    assert sample["database"]["password"] == "hunter2-planted"


@requires_core
def test_object_format_overrides(tmp_path):
    # Extensionless: sniffing alone would call a leading { JSONL, so
    # the explicit format is the documented route; --format json on a
    # .json file dispatches on the top-level shape by itself.
    bare = _write(tmp_path, "settings", {"a": 1})
    out = run_schema(bare, "--format", "json-object")
    assert out["format"] == "json-object"
    named = _write(tmp_path, "settings.json", {"a": 1})
    out = run_schema(named, "--format", "json")
    assert out["format"] == "json-object"
    out = run_schema(named)
    assert out["format"] == "json-object"


@requires_core
def test_array_records_get_the_same_nested_redaction(tmp_path):
    # Consistency: nested values inside JSON array records are held
    # to the same rule as nested values inside a top-level object.
    path = _write(tmp_path, "rows.json",
                  [{"id": 1, "meta": {"api_token": TOKEN}}])
    proc, manifest = run_pack(path, tmp_path / "pack")
    assert_no_canaries_in_tree(
        tmp_path / "pack", extra_texts=[proc.stdout, proc.stderr])
    nested = {c["name"] for c in manifest["redaction"]["nested"]}
    assert nested == {"meta.api_token"}
    sample = json.loads((tmp_path / "pack" / manifest["sample"]["file"]
                         ).read_text(encoding="utf-8"))
    assert sample[0]["meta"]["api_token"] == "[REDACTED]"
    assert sample[0]["id"] == 1
