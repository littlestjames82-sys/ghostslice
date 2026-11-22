"""Pack generation: draft only, no invented details, no em dashes.

PLAN rules under test:
  - No selector packs the single highest scoring lead only.
  - Every pack says DRAFT ONLY / not sent, carries a verification
    checklist and a re-verify warning, and names Ghost Developer
    Studio, Ryan Cotten, and a free custom website concept offer.
  - The studio public contact (423) 408-2150 may appear only as the
    studio contact, never as the lead's phone.
  - A pack contains no business detail that is not in the stored
    record: a sparse lead with no trade, town, phone, email, rating,
    or website data gets blanks, no guessed angle, and no invented
    phone number, price, URL, or rating anywhere in its pack.
"""
import re

from conftest import (all_pack_text, import_leads, out_text, pack,
                      pack_texts)

EM_DASH = "\u2014"
PHONE_RE = re.compile(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b|\(\d{3}\)\s*\d{3}")


def _packed(tmp_path, fixture="scoring_leads.csv", *extra):
    proc, store = import_leads(tmp_path, fixture)
    assert proc.returncode == 0, out_text(proc)
    out_dir = tmp_path / "packs"
    proc = pack(store, out_dir, *extra)
    assert proc.returncode == 0, out_text(proc)
    return out_dir


def test_default_pack_is_highest_lead_only(tmp_path):
    out_dir = _packed(tmp_path)
    texts = pack_texts(out_dir)
    assert len(texts) == 1, f"default pack flooded the disk: {texts}"
    only = next(iter(texts.values()))
    assert "Hilltop Quarry" in only


def test_pack_all_covers_every_lead_and_is_marked_draft(tmp_path):
    out_dir = _packed(tmp_path, "scoring_leads.csv", "--all")
    texts = pack_texts(out_dir)
    assert len(texts) == 5, texts.keys()
    for name, text in texts.items():
        low = text.lower()
        assert "draft" in low, f"{name} is not marked as a draft"
        assert "not sent" in low, f"{name} lacks the not sent line"
        assert EM_DASH not in text, f"{name} contains an em dash"
        assert "ghost developer studio" in low
        assert "ryan cotten" in low
        assert "free" in low and "website" in low, \
            f"{name} lacks the free website concept offer"
        assert "checklist" in low or "verify" in low or \
            "re-check" in low or "recheck" in low, \
            f"{name} lacks a verification step"


def test_pack_uses_only_stored_facts_for_a_full_lead(tmp_path):
    out_dir = _packed(tmp_path, "scoring_leads.csv", "--all")
    text = all_pack_text(out_dir)
    hill = [t for t in pack_texts(out_dir).values()
            if "Hilltop Quarry" in t][0]
    for fact in ("Hauling", "Exampleton", "423-555-0142", "3.7"):
        assert fact in hill, f"stored fact {fact} missing from pack"
    # Score snapshot with reasons is present.
    assert "85" in hill
    low = hill.lower()
    assert "dead" in low and "unclaimed" in low


def test_sparse_lead_pack_invents_nothing(tmp_path):
    out_dir = _packed(tmp_path, "sparse_lead.csv", "--all")
    texts = pack_texts(out_dir)
    assert len(texts) == 1, texts.keys()
    text = next(iter(texts.values()))
    assert "Mystery Works" in text
    assert EM_DASH not in text
    low = text.lower()
    # No guessed angle for unknown fields.
    for invented_angle in ("dead website", "dead site",
                           "unclaimed", "no dedicated website",
                           "low rating", "reputation"):
        assert invented_angle not in low, \
            f"sparse pack states an angle it cannot know: {invented_angle}"
    # No invented money, rating, or web address.
    assert "$" not in text, "sparse pack invented a price"
    assert "http://" not in low and "https://" not in low
    assert ".com" not in low and ".example" not in low
    # The only phone-shaped number allowed is the studio contact.
    phones = PHONE_RE.findall(text)
    normalised = [re.sub(r"\D", "", p) for p in
                  re.findall(r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}", text)]
    for digits in normalised:
        assert digits == "4234082150", \
            f"sparse pack invented a phone number: {digits}"
    assert phones is not None  # regex sanity, real check is above
