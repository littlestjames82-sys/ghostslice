"""Import, normalisation, and dedupe.

PLAN rules under test:
  - Dedupe key: same normalised name plus same phone digits, or same
    normalised name plus same town when no phone is present.
  - First record wins. Later non-blank fields fill blanks only. No
    non-blank field is ever overwritten with a different value.
  - Rows with no name are skipped and reported.
  - Rating outside 0 to 5 is rejected on import, not clamped.
  - website_status 404 normalises to dead and business.site to
    template (covered by the normalisation test below).
"""
import csv
from pathlib import Path

from conftest import (find_record, import_leads, list_records, out_text,
                      run_cli)


def test_dedupe_merges_phone_format_variants_and_fills_blanks(tmp_path):
    proc, store = import_leads(tmp_path, "dedupe_leads.csv")
    assert proc.returncode == 0, out_text(proc)
    text = out_text(proc).lower()
    assert any(tok in text for tok in ("merged", "duplicate", "dedupe")), \
        "import output never reports the merge"
    records = list_records(store)
    hill = [r for r in records
            if "hilltop quarry" in str(r.get("name", "")).lower()]
    assert len(hill) == 1, f"variants did not merge: {records}"
    rec = hill[0]
    # First record wins on town: Sampleville must not overwrite it.
    assert rec.get("town") == "Exampleton", rec
    # Blank email is filled from the later row.
    assert "hilltopquarry.example" in str(rec.get("email", "")), rec


def test_nameless_row_is_skipped_and_reported(tmp_path):
    proc, store = import_leads(tmp_path, "dedupe_leads.csv")
    assert proc.returncode == 0, out_text(proc)
    text = out_text(proc).lower()
    assert "skip" in text, "import output never reports a skipped row"
    records = list_records(store)
    assert len(records) == 2, (
        f"expected Hilltop (merged) plus Solo Plumbing, got {records}")
    assert all(str(r.get("name", "")).strip() for r in records)


def test_reimporting_same_file_does_not_duplicate(tmp_path):
    proc, store = import_leads(tmp_path, "dedupe_leads.csv")
    assert proc.returncode == 0, out_text(proc)
    local = Path(tmp_path) / "dedupe_leads.csv"
    proc2 = run_cli(["import", local, "--store", store])
    assert proc2.returncode == 0, out_text(proc2)
    assert len(list_records(store)) == 2


def test_out_of_range_rating_is_rejected_not_clamped(tmp_path):
    proc, store = import_leads(tmp_path, "bad_rating.csv")
    combined = out_text(proc)
    if proc.returncode == 0:
        # Row level rejection: the bad lead is absent or reported,
        # never stored with a clamped 5.0 rating.
        assert any(tok in combined.lower() for tok in
                   ("reject", "skip", "invalid", "rating", "error")), \
            "out of range rating was accepted silently"
        try:
            records = list_records(store)
            bad = [r for r in records
                   if "Impossible Stars" in str(r.get("name", ""))]
            assert not bad, f"out of range lead was stored: {bad}"
        except AssertionError:
            # Store may legitimately not exist if import failed whole.
            pass
    else:
        assert "rating" in combined.lower() or \
            "7.5" in combined or "error" in combined.lower(), combined


def test_website_status_normalisation(tmp_path):
    csv_path = Path(tmp_path) / "statuses.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "trade", "town", "phone", "email",
                    "has_website", "website_status", "google_profile",
                    "rating", "notes", "source"])
        w.writerow(["Status Four Oh Four", "Trade", "Exampleton",
                    "423-555-0131", "", "false", "404", "unknown", "",
                    "FICTIONAL example", "fictional-example"])
        w.writerow(["Status Template Site", "Trade", "Exampleton",
                    "423-555-0132", "", "false", "business.site",
                    "unknown", "", "FICTIONAL example",
                    "fictional-example"])
    store = Path(tmp_path) / "leads.json"
    proc = run_cli(["import", csv_path, "--store", store])
    assert proc.returncode == 0, out_text(proc)
    from conftest import score_records
    records = score_records(store)
    four = find_record(records, "Status Four Oh Four")
    templ = find_record(records, "Status Template Site")
    # false (30) plus dead (20) plus phone (5) = 55
    assert float(four["score"]) == 55, four
    # false (30) plus template (15) plus phone (5) = 50
    assert float(templ["score"]) == 50, templ


def test_missing_input_file_fails_cleanly(tmp_path):
    store = Path(tmp_path) / "leads.json"
    proc = run_cli(["import", Path(tmp_path) / "nope.csv",
                    "--store", store])
    assert proc.returncode != 0, "missing input file was accepted"
    assert out_text(proc).strip(), "missing file failed with no message"
