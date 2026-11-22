"""Fixture sanity. These need no GhostLeads core: they prove the
fixtures themselves have the properties the behavioural tests rely on,
and that every example business is clearly fictional."""
import csv
import json
import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLES = FIXTURES.parents[1] / "examples"
EM_DASH = "\u2014"


def _csv_rows(name):
    with open(FIXTURES / name, newline="") as fh:
        return list(csv.DictReader(fh))


def test_scoring_csv_has_required_columns_and_fictional_rows():
    rows = _csv_rows("scoring_leads.csv")
    assert rows, "scoring fixture is empty"
    for col in ("name", "trade", "town", "phone", "has_website",
                "website_status", "google_profile", "rating"):
        assert col in rows[0], f"missing column {col}"
    for row in rows:
        assert "FICTIONAL" in row["notes"]
        assert row["source"] == "fictional-example"


def test_scoring_fixture_score_math_is_as_documented():
    # PLAN scoring: no website 30, dead 20, unclaimed 20, rating <3.8
    # 10, phone 5, email 5. Hilltop: 30+20+20+10+5 = 85.
    rows = {r["name"]: r for r in _csv_rows("scoring_leads.csv")}
    hill = rows["Hilltop Quarry Hauling"]
    assert hill["has_website"] == "false"
    assert hill["website_status"] == "dead"
    assert hill["google_profile"] == "unclaimed"
    assert float(hill["rating"]) == 3.7
    maple = rows["Maple Street Corner Bakery"]
    assert maple["has_website"] == "true"
    assert maple["website_status"] == "live"
    assert maple["google_profile"] == "claimed"


def test_all_fixture_phones_are_555_fictional_numbers():
    for name in ("scoring_leads.csv", "dedupe_leads.csv",
                 "sparse_lead.csv", "bad_rating.csv"):
        for row in _csv_rows(name):
            phone = (row.get("phone") or "").strip()
            if phone:
                digits = re.sub(r"\D", "", phone)
                assert "55501" in digits, f"non-fictional phone {phone}"


def test_json_fixture_matches_csv_high_and_low_leads():
    data = json.loads((FIXTURES / "leads.json").read_text())
    leads = data["leads"] if isinstance(data, dict) else data
    names = {lead["name"] for lead in leads}
    assert names == {"Hilltop Quarry Hauling",
                     "Maple Street Corner Bakery"}
    for lead in leads:
        assert "FICTIONAL" in lead["notes"]


def test_dedupe_fixture_variants_share_phone_digits():
    rows = _csv_rows("dedupe_leads.csv")
    variants = [r for r in rows
                if "hilltop quarry" in (r["name"] or "").lower()]
    assert len(variants) == 2
    digits = {re.sub(r"\D", "", r["phone"]) for r in variants}
    assert len(digits) == 1, "variants must share one phone digit string"
    # First row wins on town; the later row carries the email that may
    # fill a blank only.
    assert variants[0]["town"] == "Exampleton"
    assert variants[0]["email"] == ""
    assert variants[1]["email"].endswith(".example")


def test_examples_are_fictional_and_have_no_em_dash():
    sample = EXAMPLES / "sample_leads.csv"
    assert sample.exists(), "examples/sample_leads.csv missing"
    text = sample.read_text()
    assert EM_DASH not in text
    with open(sample, newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "sample leads are empty"
    for row in rows:
        assert "FICTIONAL" in (row.get("notes") or "")
