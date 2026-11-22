"""Harden round regressions (Oct 18, 2026 improvement pass).

Each test pins a defect found by probing malformed inputs, corrupt
stores, and dedupe edge cases against the pre-harden code:

  - a BOM-saved store failed to load at all
  - a store whose top level / leads value was not a list crashed the
    CLI with a TypeError traceback; a store object without a leads
    key silently read as empty (and the next save would wipe it)
  - a JSON import object without a leads key silently imported zero
    rows and reported success
  - an oversized CSV field raised a raw csv.Error traceback, and a
    duplicate CSV header silently discarded a column
  - NUL / control bytes in a cell survived into stored names
  - nested list/dict field values were stringified into fake names
    and phones (Python reprs) instead of being rejected
  - accented name variants and punctuated town variants never merged
  - a phone listed with an extension never matched the same line
    listed without one
  - a stored boolean score/tier became score 1 / invalid tier 0, and
    stored score reasons reached packs unsanitised
  - pack --out pointing at an existing file crashed with a traceback

All businesses are fictional, all phones 555.
"""
import json
import sys
from pathlib import Path

import pytest

from conftest import SRC, out_text, run_cli

sys.path.insert(0, str(SRC))

from ghostleads.models import Lead, _clean, phone_digits  # noqa: E402
from ghostleads.store import load_store, read_import_file, same_lead  # noqa: E402


def _store_file(tmp_path, payload_bytes, name="leads.json"):
    path = Path(tmp_path) / name
    path.write_bytes(payload_bytes)
    return path


# --- store loading ---------------------------------------------------

def test_bom_saved_store_loads(tmp_path):
    payload = json.dumps({"leads": [{"name": "Bom Store Fictional Works"}]})
    store = _store_file(tmp_path, b"\xef\xbb\xbf" + payload.encode("utf-8"))
    assert [lead.name for lead in load_store(store)] == [
        "Bom Store Fictional Works"]
    proc = run_cli(["score", "--store", store])
    assert proc.returncode == 0, out_text(proc)


def test_corrupt_store_shapes_raise_value_error_not_type_error(tmp_path):
    for payload in ("123", '"just a string"',
                    json.dumps({"leads": 123}),
                    json.dumps({"version": 1, "tool": "ghostleads"})):
        store = _store_file(tmp_path, payload.encode("utf-8"))
        with pytest.raises(ValueError):
            load_store(store)


def test_corrupt_store_fails_cleanly_via_cli_without_traceback(tmp_path):
    store = _store_file(tmp_path, b"123")
    proc = run_cli(["score", "--store", store])
    assert proc.returncode == 2, out_text(proc)
    assert "Traceback" not in out_text(proc)
    assert "error" in out_text(proc).lower()


def test_stored_boolean_score_and_tier_do_not_become_numbers():
    lead = Lead.from_dict({"name": "Bool Score Fictional", "score": True,
                           "tier": False, "rating": 4})
    assert lead.score == 0, lead
    assert lead.tier == 3, lead


def test_stored_reasons_are_sanitised_to_single_lines():
    lead = Lead.from_dict({"name": "Reason Fictional",
                           "reasons": ["ok reason\n## Injected Heading",
                                       {"odd": "object"}]})
    assert all("\n" not in r for r in lead.reasons)
    assert all(isinstance(r, str) for r in lead.reasons)


# --- import parsing ----------------------------------------------------

def test_json_import_object_without_leads_key_is_an_error(tmp_path):
    for payload in ({"name": "Single Object Fictional"},
                    {"lead": [{"name": "Typo Key Fictional"}]}):
        path = Path(tmp_path) / "imp.json"
        path.write_text(json.dumps(payload))
        with pytest.raises(ValueError):
            read_import_file(path)
    proc = run_cli(["import", path, "--store", Path(tmp_path) / "s.json"])
    assert proc.returncode == 2, out_text(proc)
    assert "Traceback" not in out_text(proc)


def test_json_import_leads_key_is_case_insensitive(tmp_path):
    path = Path(tmp_path) / "imp.json"
    path.write_text(json.dumps({"Leads": [{"name": "Capital Key Fictional"}]}))
    rows = read_import_file(path)
    assert rows == [{"name": "Capital Key Fictional"}]


def test_oversized_csv_field_is_a_clean_value_error(tmp_path):
    path = Path(tmp_path) / "big.csv"
    path.write_text("name,notes\nBig Fictional Works," + "x" * 200_000 + "\n")
    with pytest.raises(ValueError):
        read_import_file(path)
    proc = run_cli(["import", path, "--store", Path(tmp_path) / "s.json"])
    assert proc.returncode == 2, out_text(proc)
    assert "Traceback" not in out_text(proc)


def test_duplicate_csv_header_is_rejected(tmp_path):
    path = Path(tmp_path) / "dup.csv"
    path.write_text("name,town,name\nDup Fictional,Exampleton,Other\n")
    with pytest.raises(ValueError):
        read_import_file(path)


def test_control_characters_are_stripped_from_fields():
    assert _clean("Bad\x00Name\x07 Works") == "BadName Works"
    lead = Lead.from_row({"name": "Nul\x00 Fictional Works"})
    assert "\x00" not in lead.name


def test_nested_field_values_are_rejected_not_stringified():
    with pytest.raises(ValueError):
        Lead.from_row({"name": {"first": "Foo"}})
    with pytest.raises(ValueError):
        Lead.from_row({"name": "Fine Fictional", "phone": [423, 555, 100]})
    with pytest.raises(ValueError):
        Lead.from_dict({"name": ["Foo", "Bar"]})


# --- dedupe edge cases -------------------------------------------------

def test_accented_name_variants_merge():
    a = Lead(name="Café René Fictional Works", town="Exampleton")
    b = Lead(name="Cafe Rene Fictional Works", town="Exampleton")
    assert same_lead(a, b)


def test_town_punctuation_variants_merge():
    a = Lead(name="Punct Fictional Works", town="St. Marys")
    b = Lead(name="Punct Fictional Works", town="St Marys,")
    assert same_lead(a, b)


def test_phone_extension_variant_matches_plain_number():
    assert phone_digits("423-555-0100 ext. 12") == \
        phone_digits("(423) 555-0100") == "4235550100"
    a = Lead(name="Ext Fictional Works", phone="423-555-0100 x12",
             town="Exampleton")
    b = Lead(name="Ext Fictional Works", phone="(423) 555-0100",
             town="Sampleville")
    assert same_lead(a, b)


# --- CLI write failures -------------------------------------------------

def test_pack_out_pointing_at_a_file_fails_cleanly(tmp_path):
    store = _store_file(
        tmp_path,
        json.dumps({"leads": [{"name": "Pack Fictional Works"}]}).encode())
    out_file = Path(tmp_path) / "afile"
    out_file.write_text("not a directory")
    proc = run_cli(["pack", "--store", store, "--out", out_file])
    assert proc.returncode == 2, out_text(proc)
    assert "Traceback" not in out_text(proc)
    assert "error" in out_text(proc).lower()
