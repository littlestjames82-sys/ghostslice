"""Deepen round: near-spelling (fuzzy) dedupe for directory variants.

The standing miss from PLAN.md: the same business listed as "Dautel"
in one directory and "Dautell" in another never merged, because the
name match was exact-only. The new path merges near-spelling variants
only with corroboration from other known fields, and never when both
phones are present and differ. All businesses are fictional, all
phones 555.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostleads.models import Lead, edit_distance, fuzzy_name_match
from ghostleads.store import same_lead

from conftest import list_records, out_text, run_cli

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


def _import(tmp_path, path, store_name="leads.json"):
    store = Path(tmp_path) / store_name
    proc = run_cli(["import", path, "--store", store])
    assert proc.returncode == 0, out_text(proc)
    return store


# --- edit_distance / fuzzy_name_match units -------------------------

def test_edit_distance_counts_transposition_as_one():
    assert edit_distance("johnson", "johnosn") == 1
    assert edit_distance("dautel", "dautell") == 1
    assert edit_distance("same", "same") == 0
    assert edit_distance("", "abc") == 3


def test_fuzzy_name_match_accepts_single_word_typos():
    assert fuzzy_name_match("Dautel Excavating", "Dautell Excavating")
    assert fuzzy_name_match("Johnson Tree Care", "Johnosn Tree Care")
    # Two slips are allowed only inside a long word.
    assert fuzzy_name_match("Robertson Hauling", "Roburtsen Hauling")


def test_fuzzy_name_match_rejects_non_variants():
    # Identical after normalisation is the exact match, not fuzzy.
    assert not fuzzy_name_match("Dautel Excavating", "Dautel Excavating")
    assert not fuzzy_name_match("C & C Ready Mix", "C and C Ready Mix")
    # More than one word differs.
    assert not fuzzy_name_match("Maple Street Bakery", "Mapel Street Bakary")
    # Differing word changes its first letter.
    assert not fuzzy_name_match("Tree Pros", "Free Pros")
    # Differing word is too short to trust.
    assert not fuzzy_name_match("Oak Tree Care", "Oaks Tree Care")
    # Unrelated names of the same shape.
    assert not fuzzy_name_match("Johnson Hauling", "Jackson Hauling")
    # Different word counts.
    assert not fuzzy_name_match("Dautel", "Dautel Excavating")


# --- same_lead corroboration rules ----------------------------------

def _lead(**kw):
    base = dict(name="Dautel Excavating", trade="Excavating",
                town="Exampleton")
    base.update(kw)
    return Lead(**base)


def test_fuzzy_same_phone_merges_even_if_town_spelling_differs():
    a = _lead(phone="423-555-0100", town="Exampleton")
    b = _lead(name="Dautell Excavating", phone="(423) 555-0100",
              town="Sampleville")
    assert same_lead(a, b)


def test_fuzzy_different_phones_never_merge():
    a = _lead(phone="423-555-0100", rating=4.0)
    b = _lead(name="Dautell Excavating", phone="423-555-0999",
              rating=4.0)
    assert not same_lead(a, b)


def test_fuzzy_no_phone_merges_on_town_trade_and_attribute():
    a = _lead(rating=3.7, website_status="dead")
    b = _lead(name="Dautell Excavating", rating=3.7,
              website_status="dead")
    assert same_lead(a, b)


def test_fuzzy_no_phone_merges_on_town_and_email():
    a = _lead(email="crew@dautel.example", trade="")
    b = _lead(name="Dautell Excavating", email="crew@dautel.example",
              trade="")
    assert same_lead(a, b)


def test_fuzzy_town_and_trade_alone_do_not_merge():
    # Same town and same generic trade, but no agreeing known
    # attribute and no email: two distinct firms stay separate.
    a = _lead()
    b = _lead(name="Dautell Excavating")
    assert not same_lead(a, b)
    # Differing known attributes are positive evidence against.
    a2 = _lead(rating=3.7, website_status="dead")
    b2 = _lead(name="Dautell Excavating", rating=4.9,
               website_status="live")
    assert not same_lead(a2, b2)


def test_fuzzy_different_towns_do_not_merge_without_phone():
    a = _lead(rating=3.7)
    b = _lead(name="Dautell Excavating", town="Sampleville", rating=3.7)
    assert not same_lead(a, b)


def test_exact_name_rules_are_unchanged():
    # Sparse exact re-import still merges (blank town on both sides).
    assert same_lead(Lead(name="Mystery Works"), Lead(name="Mystery Works"))
    # Exact name with different phones still never merges.
    assert not same_lead(_lead(phone="423-555-0100"),
                         _lead(phone="423-555-0999"))


# --- end to end through the CLI --------------------------------------

def test_cli_merges_misspelled_duplicate_and_fills_blanks(tmp_path):
    path = _write_csv(tmp_path, [
        ["Dautel Fictional Excavating", "Excavating", "Exampleton",
         "423-555-0140", "", "false", "dead", "unclaimed", "3.7",
         "FICTIONAL example", "fictional-example"],
        ["Dautell Fictional Excavating", "Excavating", "Exampleton",
         "(423) 555-0140", "crew@dautell.example", "false", "dead",
         "unclaimed", "3.7", "FICTIONAL example", "fictional-example"],
    ])
    store = _import(tmp_path, path)
    records = list_records(store)
    assert len(records) == 1, records
    # First record wins on the display name; blank email is filled.
    assert records[0].get("name") == "Dautel Fictional Excavating"
    assert "dautell.example" in str(records[0].get("email", ""))


def test_cli_merges_phoneless_misspelling_with_corroboration(tmp_path):
    path = _write_csv(tmp_path, [
        ["Dautel Fictional Excavating", "Excavating", "Exampleton",
         "", "", "false", "dead", "unclaimed", "3.7",
         "FICTIONAL example", "fictional-example"],
        ["Dautell Fictional Excavating", "Excavating", "Exampleton",
         "", "crew@dautell.example", "false", "dead", "unclaimed",
         "3.7", "FICTIONAL example", "fictional-example"],
    ])
    store = _import(tmp_path, path)
    assert len(list_records(store)) == 1


def test_cli_keeps_similar_but_distinct_businesses_separate(tmp_path):
    path = _write_csv(tmp_path, [
        ["Smith Fictional Plumbing", "Plumbing", "Exampleton",
         "423-555-0111", "", "false", "none", "unknown", "4.8",
         "FICTIONAL example", "fictional-example"],
        ["Smyth Fictional Plumbing", "Plumbing", "Exampleton",
         "423-555-0222", "", "false", "dead", "unclaimed", "3.1",
         "FICTIONAL example", "fictional-example"],
    ])
    store = _import(tmp_path, path)
    assert len(list_records(store)) == 2
