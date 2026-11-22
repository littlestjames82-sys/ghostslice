"""Hardening regression tests (Oct 18, 2026 improvement wave).

Each test pins a bug found by auditing the v0.1 core against the
hard rules in PLAN.md / README.md: sensitive values are never
sampled or stored, row counts are true counts, memory and errors
stay bounded and stated. Every test here fails on the pre-hardening
code and passes on the fixed code.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from conftest import (ROOT, column, requires_core, run_cli, run_pack,
                      run_schema)

CARD = "4111111111111111"  # public Visa test number, Luhn-valid


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _write_bytes(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --- UTF-8 BOM handling -------------------------------------------------

@requires_core
def test_bom_csv_header_is_clean_and_redaction_still_applies(tmp_path):
    path = _write_bytes(
        tmp_path, "bom.csv",
        b"\xef\xbb\xbfid,email\n1,a@example.com\n2,b@example.com\n")
    out = run_schema(path)
    assert [c["name"] for c in out["columns"]] == ["id", "email"]
    assert {c["name"] for c in out["redacted_columns"]} == {"email"}


@requires_core
def test_bom_json_array_and_object_are_not_rejected_as_scalars(tmp_path):
    arr = _write_bytes(tmp_path, "bom.json",
                       b'\xef\xbb\xbf[{"id": 1}, {"id": 2}]')
    out = run_schema(arr)
    assert out["counts"]["rows_parsed"] == 2
    obj = _write_bytes(tmp_path, "bomobj.json",
                       b'\xef\xbb\xbf{"id": 1, "name": "x"}')
    out = run_schema(obj)
    assert out["counts"]["rows_parsed"] == 1


@requires_core
def test_bom_jsonl_first_record_is_not_counted_malformed(tmp_path):
    path = _write_bytes(
        tmp_path, "bom.jsonl",
        b'\xef\xbb\xbf{"id": 1, "first_only": 1}\n{"id": 2}\n')
    out = run_schema(path)
    assert out["counts"]["rows_parsed"] == 2
    assert out["counts"]["rows_malformed"] == 0
    # the first record's unique key must reach the schema
    assert "first_only" in [c["name"] for c in out["columns"]]


# --- Delimited reader counts and errors ---------------------------------

@requires_core
def test_leading_blank_lines_do_not_corrupt_csv_counts(tmp_path):
    path = _write(tmp_path, "blank.csv",
                  "\n\nid,name\n1,alice\n2,bob\n")
    out = run_schema(path)
    assert out["counts"]["rows_parsed"] == 2
    assert out["counts"]["rows_total"] == 2
    proc, manifest = run_pack(path, tmp_path / "pack")
    sample_text = (tmp_path / "pack" / manifest["sample"]["file"]).read_text(
        encoding="utf-8")
    lines = sample_text.splitlines()
    assert lines == ["id,name", "1,alice", "2,bob"]


@requires_core
def test_duplicate_header_suffix_never_collides(tmp_path):
    path = _write(tmp_path, "dup.csv", "a,a#2,a\n1,2,3\n")
    out = run_schema(path)
    names = [c["name"] for c in out["columns"]]
    assert names == ["a", "a#2", "a#3"]
    assert len(set(names)) == 3


@requires_core
def test_oversized_csv_field_is_a_clean_error_not_a_traceback(tmp_path):
    path = _write(tmp_path, "big.csv", "id,txt\n1," + "x" * 200000 + "\n")
    proc = run_cli(["schema", path])
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "field larger than field limit" in proc.stderr


# --- JSON array structure and chunk boundaries ---------------------------

@requires_core
def test_json_array_separator_errors_are_counted_malformed(tmp_path):
    cases = {
        "trailing": "[1, 2,]",
        "missing": "[1 2]",
        "double": "[1,, 2]",
        "garbage": '[{"a": 1}] trailing',
    }
    for name, text in cases.items():
        path = _write(tmp_path, name + ".json", text)
        out = run_schema(path)
        counts = out["counts"]
        assert counts["rows_malformed"] >= 1, (name, counts)
        assert counts["truncated"] is True, (name, counts)


@requires_core
def test_json_array_number_split_across_chunks_stays_one_element(tmp_path):
    # A 100-digit number starting just before the reader's 64 KiB
    # chunk boundary: its 1-digit prefix is itself a valid JSON
    # number, and used to be emitted as a separate element, splitting
    # one value into two rows and corrupting the true count.
    text = '["' + "a" * 65530 + '", ' + "7" * 100 + "]"
    path = _write(tmp_path, "split.json", text)
    out = run_schema(path)
    assert out["counts"]["rows_parsed"] == 2
    assert out["counts"]["rows_malformed"] == 0
    col = column(out, "value")
    assert col["distinct_count"] == 2
    assert col["min"] == int("7" * 100)
    assert col["max"] == int("7" * 100)


# --- Deep nesting --------------------------------------------------------

@requires_core
def test_deeply_nested_object_analyzes_instead_of_recursion_error(tmp_path):
    depth = 800
    path = _write(tmp_path, "deep.json",
                  '{"a":' * depth + "1" + "}" * depth)
    out = run_schema(path)
    assert out["counts"]["rows_parsed"] == 1
    assert out["structure"]["max_depth"] == depth
    assert out["structure"]["total_keys"] == depth


@requires_core
def test_deeply_nested_jsonl_value_packs(tmp_path):
    depth = 800
    path = _write(tmp_path, "deep.jsonl",
                  '{"a":' + "[" * depth + "1" + "]" * depth + "}\n")
    proc, manifest = run_pack(path, tmp_path / "pack")
    assert manifest["counts"]["rows_parsed"] == 1
    assert manifest["sample"]["rows"] == 1


# --- Non-finite numbers ---------------------------------------------------

def _strict_loads(text):
    def reject(value):
        raise ValueError("non-strict JSON constant: %s" % value)
    return json.loads(text, parse_constant=reject)


@requires_core
def test_nonfinite_values_stay_out_of_ranges_and_manifest(tmp_path):
    path = _write(tmp_path, "nan.json",
                  '[{"v": NaN}, {"v": Infinity}, {"v": 1.5}]')
    proc = run_cli(["schema", path])
    assert proc.returncode == 0, proc.stderr
    out = _strict_loads(proc.stdout)  # stdout must be strict JSON
    col = column(out, "v")
    assert col["min"] == 1.5 and col["max"] == 1.5
    proc, manifest = run_pack(path, tmp_path / "pack")
    raw = (tmp_path / "pack" / "manifest.json").read_text(encoding="utf-8")
    _strict_loads(raw)  # the manifest itself must be strict JSON


@requires_core
def test_float_overflow_string_stays_out_of_range(tmp_path):
    path = _write(tmp_path, "big.csv", "v\n1e999\n2.0\n")
    out = run_schema(path)
    col = column(out, "v")
    assert col["min"] == 2.0 and col["max"] == 2.0


@requires_core
def test_nan_counts_as_one_distinct_value(tmp_path):
    path = _write(tmp_path, "nans.json",
                  '[{"v": NaN}, {"v": NaN}, {"v": 1.0}]')
    out = run_schema(path)
    assert column(out, "v")["distinct_count"] == 2


# --- Sensitive values below the column threshold ---------------------------

@requires_core
def test_lone_sensitive_value_in_plain_column_is_not_sampled(tmp_path):
    rows = ["id,notes"] + ["%d,note number %d" % (i, i) for i in range(100)]
    rows[50] = "50,leakme@example.com"
    path = _write(tmp_path, "notes.csv", "\n".join(rows) + "\n")
    proc, manifest = run_pack(path, tmp_path / "pack", "--sample", 100)
    for f in (tmp_path / "pack").rglob("*"):
        if f.is_file():
            assert "leakme@example.com" not in f.read_text(
                encoding="utf-8", errors="replace"), str(f)
    assert "leakme@example.com" not in proc.stdout + proc.stderr
    sample_text = (tmp_path / "pack" / manifest["sample"]["file"]).read_text(
        encoding="utf-8")
    assert "[REDACTED]" in sample_text
    assert "note number 51" in sample_text  # neighbours survive
    nested = {c["name"] for c in manifest["redaction"]["nested"]}
    assert "notes" in nested


@requires_core
def test_card_below_threshold_is_not_stored_as_schema_max(tmp_path):
    rows = ["amt"] + [str(i * 10) for i in range(50)] + [CARD]
    path = _write(tmp_path, "amt.csv", "\n".join(rows) + "\n")
    proc = run_cli(["schema", path])
    assert proc.returncode == 0, proc.stderr
    assert CARD not in proc.stdout
    out = json.loads(proc.stdout)
    col = column(out, "amt")
    assert col["redacted"] is False  # below the column threshold
    assert col["max"] == 490  # the largest innocuous value
    assert col["distinct_count"] == 51


# --- Name matching: whole words, not substrings ----------------------------

@requires_core
def test_name_matching_ignores_substring_lookalikes(tmp_path):
    header = ("hotel,passenger_count,footprint,compass,discard,"
              "cardinality,satellite,telephone,password_hash")
    path = _write(tmp_path, "names.csv",
                  header + "\n" + ",".join(["x"] * 9) + "\n")
    out = run_schema(path)
    recorded = {c["name"]: c["reason"] for c in out["redacted_columns"]}
    assert set(recorded) == {"telephone", "password_hash"}
    assert "phone" in recorded["telephone"]
    assert "password" in recorded["password_hash"]


@requires_core
def test_camelcase_sensitive_names_still_redacted(tmp_path):
    path = _write(tmp_path, "camel.json",
                  '{"passwordHash": "x", "apiToken": "y",'
                  ' "userEmail": "z", "displayName": "w"}')
    out = run_schema(path)
    recorded = {c["name"] for c in out["redacted_columns"]}
    assert recorded == {"passwordHash", "apiToken", "userEmail"}


# --- Sample size validation -------------------------------------------------

@requires_core
def test_sample_size_must_be_positive(tmp_path, people_csv):
    for bad in ("0", "-3"):
        proc = run_cli(["pack", people_csv, "-o", tmp_path / "p",
                        "--sample", bad])
        assert proc.returncode == 2, (bad, proc.stdout, proc.stderr)
        assert "Traceback" not in proc.stderr


# --- Pack check recounts the sample ------------------------------------------

@requires_core
def test_check_detects_a_lying_sample_row_count(tmp_path, people_csv):
    proc, manifest = run_pack(people_csv, tmp_path / "pack")
    manifest_path = tmp_path / "pack" / "manifest.json"
    manifest["sample"]["rows"] = 1  # the file still holds 5 rows
    manifest_path.write_text(json.dumps(manifest, indent=2),
                             encoding="utf-8")
    proc = run_cli(["check", tmp_path / "pack"])
    assert proc.returncode == 1, proc.stdout


@requires_core
def test_check_detects_row_indices_length_lie(tmp_path, people_csv):
    proc, manifest = run_pack(people_csv, tmp_path / "pack")
    manifest_path = tmp_path / "pack" / "manifest.json"
    manifest["sample"]["row_indices"] = manifest["sample"]["row_indices"][:-1]
    manifest_path.write_text(json.dumps(manifest, indent=2),
                             encoding="utf-8")
    proc = run_cli(["check", tmp_path / "pack"])
    assert proc.returncode == 1, proc.stdout


# --- MCP error shape -----------------------------------------------------------

def _mcp_session(requests, timeout=60):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get(
        "PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "ghostdata", "mcp"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        env=env, capture_output=True, text=True, timeout=timeout)
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()
            if line.strip()]


@requires_core
def test_mcp_missing_arguments_returns_an_rpc_error_not_a_crash():
    replies = _mcp_session([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "data_schema", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "data_pack",
                    "arguments": {"path": "/nonexistent.csv",
                                  "out": "/tmp/nowhere-pack",
                                  "sample": None}}},
    ])
    by_id = {r["id"]: r for r in replies}
    assert "error" in by_id[1], by_id
    assert "error" in by_id[2], by_id
