"""Polish round regressions, Pass 1: import and dedupe robustness.

Each test pins a defect found in the Oct 14, 2026 polish audit
(see POLISH.md). All businesses are fictional, all phones 555.
"""
import csv
import json
from pathlib import Path

from conftest import find_record, list_records, out_text, run_cli, score_records

HEADER = ["name", "trade", "town", "phone", "email", "has_website",
          "website_status", "google_profile", "rating", "notes", "source"]


def _write_csv(tmp_path, rows, name="leads.csv"):
    path = Path(tmp_path) / name
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for row in rows:
            w.writerow(row)
    return path


def _import(tmp_path, path):
    store = Path(tmp_path) / "leads.json"
    proc = run_cli(["import", path, "--store", store])
    assert proc.returncode == 0, out_text(proc)
    return store


def test_country_code_phone_variant_merges(tmp_path):
    path = _write_csv(tmp_path, [
        ["Country Code Hauling", "Hauling", "Exampleton",
         "1-423-555-0142", "", "false", "dead", "unclaimed", "3.7",
         "FICTIONAL example", "fictional-example"],
        ["Country Code Hauling", "Hauling", "Exampleton",
         "(423) 555-0142", "crew@countrycode.example", "false", "dead",
         "unclaimed", "3.7", "FICTIONAL example", "fictional-example"],
    ])
    store = _import(tmp_path, path)
    records = list_records(store)
    assert len(records) == 1, records
    assert "countrycode.example" in str(records[0].get("email", ""))


def test_mixed_phone_presence_merges_both_ways(tmp_path):
    # First record has no phone, the duplicate adds one (and an email).
    path = _write_csv(tmp_path, [
        ["Solo Fictional Plumbing", "Plumbing", "Exampleton",
         "", "", "false", "none", "unclaimed", "",
         "FICTIONAL example", "fictional-example"],
        ["Solo Fictional Plumbing", "Plumbing", "Exampleton",
         "423-555-0198", "hi@soloplumbing.example", "false", "none",
         "unclaimed", "", "FICTIONAL example", "fictional-example"],
    ], name="forward.csv")
    store = _import(tmp_path, path)
    records = list_records(store)
    assert len(records) == 1, records
    assert records[0].get("phone") == "423-555-0198", records[0]

    # Reverse order: phone first, phoneless duplicate second.
    path2 = _write_csv(tmp_path, [
        ["Solo Fictional Plumbing", "Plumbing", "Exampleton",
         "423-555-0198", "", "false", "none", "unclaimed", "",
         "FICTIONAL example", "fictional-example"],
        ["Solo Fictional Plumbing", "Plumbing", "Exampleton",
         "", "hi@soloplumbing.example", "false", "none",
         "unclaimed", "", "FICTIONAL example", "fictional-example"],
    ], name="reverse.csv")
    store2 = Path(tmp_path) / "leads2.json"
    proc = run_cli(["import", path2, "--store", store2])
    assert proc.returncode == 0, out_text(proc)
    records2 = list_records(store2)
    assert len(records2) == 1, records2
    assert "soloplumbing.example" in str(records2[0].get("email", ""))


def test_sparse_lead_reimport_does_not_duplicate_itself(tmp_path):
    # Regression for a regression: the first polish version of the
    # matching predicate required a non-blank town whenever a phone
    # was missing, so a lead with neither phone nor town duplicated
    # on every re-import. Found by re-running the walkthrough.
    from conftest import ROOT, import_leads
    proc, store = import_leads(tmp_path, "sparse_lead.csv")
    assert proc.returncode == 0, out_text(proc)
    proc2, _ = import_leads(tmp_path, "sparse_lead.csv")
    assert proc2.returncode == 0, out_text(proc2)
    assert len(list_records(store)) == 1
    # Same check on the shipped example file: 5 leads in, re-import,
    # still 5 (walkthrough section 5 makes exactly this promise).
    sample = ROOT / "examples" / "sample_leads.csv"
    store2 = Path(tmp_path) / "sample.json"
    assert run_cli(["import", sample, "--store", store2]).returncode == 0
    assert run_cli(["import", sample, "--store", store2]).returncode == 0
    assert len(list_records(store2)) == 5


def test_same_name_different_phones_do_not_merge(tmp_path):
    # Guardrail against the looser matching: two branches that share
    # a name and town but carry different phones stay separate.
    path = _write_csv(tmp_path, [
        ["Twin Branch Tree Care", "Tree service", "Exampleton",
         "423-555-0111", "", "false", "none", "unknown", "",
         "FICTIONAL example", "fictional-example"],
        ["Twin Branch Tree Care", "Tree service", "Exampleton",
         "423-555-0222", "", "false", "none", "unknown", "",
         "FICTIONAL example", "fictional-example"],
    ])
    store = _import(tmp_path, path)
    assert len(list_records(store)) == 2


def test_ampersand_and_apostrophe_name_variants_merge(tmp_path):
    path = _write_csv(tmp_path, [
        ["Buck's Fictional Heating & Air", "HVAC", "Exampleton",
         "423-555-0133", "", "false", "none", "unclaimed", "3.7",
         "FICTIONAL example", "fictional-example"],
        ["Bucks Fictional Heating and Air", "HVAC", "Exampleton",
         "423-555-0133", "hi@bucksfictional.example", "false", "none",
         "unclaimed", "3.7", "FICTIONAL example", "fictional-example"],
    ])
    store = _import(tmp_path, path)
    records = list_records(store)
    assert len(records) == 1, records
    # First record wins on the display name.
    assert records[0].get("name") == "Buck's Fictional Heating & Air"


def test_json_import_accepts_utf8_bom(tmp_path):
    path = Path(tmp_path) / "bom.json"
    payload = {"leads": [{"name": "Bom Fictional Works",
                          "town": "Exampleton",
                          "notes": "FICTIONAL example",
                          "source": "fictional-example"}]}
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))
    store = _import(tmp_path, path)
    names = [str(r.get("name")) for r in list_records(store)]
    assert names == ["Bom Fictional Works"], names


def test_boolean_rating_row_is_skipped_not_scored_as_one(tmp_path):
    path = Path(tmp_path) / "bool.json"
    path.write_text(json.dumps({"leads": [
        {"name": "Bool Rating Fictional Diner", "rating": True,
         "notes": "FICTIONAL example", "source": "fictional-example"},
        {"name": "Fine Fictional Diner", "rating": 4.1,
         "notes": "FICTIONAL example", "source": "fictional-example"},
    ]}))
    store = Path(tmp_path) / "leads.json"
    proc = run_cli(["import", path, "--store", store])
    assert proc.returncode == 0, out_text(proc)
    assert "skip" in out_text(proc).lower(), out_text(proc)
    names = [str(r.get("name")) for r in list_records(store)]
    assert names == ["Fine Fictional Diner"], names


def test_corrupt_store_values_fail_cleanly_without_traceback(tmp_path):
    for bad in ({"name": "Bad Rating Store", "rating": "high"},
                {"name": "Bad Status Store", "website_status": "bogus"}):
        store = Path(tmp_path) / "leads.json"
        store.write_text(json.dumps(
            {"version": 1, "tool": "ghostleads", "leads": [bad]}))
        proc = run_cli(["score", "--store", store])
        assert proc.returncode == 2, out_text(proc)
        assert "Traceback" not in out_text(proc), out_text(proc)
        assert "error" in out_text(proc).lower()


def test_rating_boundaries_score_exactly(tmp_path):
    rows = []
    for i, rating in enumerate(("3.79", "3.8", "4.49", "4.5")):
        rows.append([f"Boundary Fictional {rating}", "Trade",
                     "Exampleton", f"423-555-010{i}", "", "", "unknown",
                     "unknown", rating, "FICTIONAL example",
                     "fictional-example"])
    path = _write_csv(tmp_path, rows)
    store = _import(tmp_path, path)
    records = score_records(store)
    # Rating points only, plus phone +5: below 3.8 is +10, exactly
    # 3.8 and 4.49 are middle +3, exactly 4.5 is +8.
    assert float(find_record(records, "Boundary Fictional 3.79")["score"]) == 15
    assert float(find_record(records, "Boundary Fictional 3.8")["score"]) == 8
    assert float(find_record(records, "Boundary Fictional 4.49")["score"]) == 8
    assert float(find_record(records, "Boundary Fictional 4.5")["score"]) == 13


def test_newline_in_name_cannot_inject_pack_structure(tmp_path):
    path = _write_csv(tmp_path, [
        ["Multi Line\n## Injected Heading Works", "Trade", "Exampleton",
         "423-555-0144", "", "false", "none", "unknown", "",
         "FICTIONAL example", "fictional-example"],
    ])
    store = _import(tmp_path, path)
    records = list_records(store)
    assert "\n" not in str(records[0].get("name", ""))
    out_dir = Path(tmp_path) / "packs"
    proc = run_cli(["pack", "--store", store, "--out", out_dir, "--all"])
    assert proc.returncode == 0, out_text(proc)
    text = next(iter(out_dir.glob("*.md"))).read_text()
    headings = [ln for ln in text.splitlines() if ln.startswith("## Injected")]
    assert not headings, text
    assert text.count("# Pitch Pack (Draft)") == 1, text
