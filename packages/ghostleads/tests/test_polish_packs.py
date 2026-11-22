"""Polish round regressions, Pass 2: pack quality.

Each test pins a defect found in the Oct 14, 2026 polish audit
(see POLISH.md). All businesses are fictional, all phones 555.
"""
import csv
from pathlib import Path

from conftest import import_leads, list_records, out_text, pack, pack_texts, run_cli

HEADER = ["name", "trade", "town", "phone", "email", "has_website",
          "website_status", "google_profile", "rating", "notes", "source"]


def _import_rows(tmp_path, rows):
    path = Path(tmp_path) / "leads.csv"
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for row in rows:
            w.writerow(row)
    store = Path(tmp_path) / "leads.json"
    proc = run_cli(["import", path, "--store", store])
    assert proc.returncode == 0, out_text(proc)
    return store


def test_slug_collision_leads_each_get_their_own_pack(tmp_path):
    store = _import_rows(tmp_path, [
        ["Cedar Fictional Signs!", "Signs", "Exampleton", "423-555-0173",
         "", "false", "template", "listing-only", "4.8",
         "FICTIONAL example", "fictional-example"],
        ["Cedar Fictional Signs", "Signs", "Sampleville", "423-555-0174",
         "", "false", "none", "unknown", "",
         "FICTIONAL example", "fictional-example"],
    ])
    out_dir = Path(tmp_path) / "packs"
    proc = pack(store, out_dir, "--all")
    assert proc.returncode == 0, out_text(proc)
    texts = pack_texts(out_dir)
    assert len(texts) == 2, texts.keys()
    joined = "\n".join(texts.values())
    assert "Exampleton" in joined and "Sampleville" in joined, texts


def test_conflicting_website_fields_are_flagged_in_pack(tmp_path):
    store = _import_rows(tmp_path, [
        ["Conflict Fictional Co", "Trade", "Exampleton", "423-555-0150",
         "", "false", "live", "unknown", "",
         "FICTIONAL example", "fictional-example"],
        ["Coherent Fictional Co", "Trade", "Exampleton", "423-555-0151",
         "", "false", "dead", "unknown", "",
         "FICTIONAL example", "fictional-example"],
    ])
    out_dir = Path(tmp_path) / "packs"
    proc = pack(store, out_dir, "--all")
    assert proc.returncode == 0, out_text(proc)
    texts = pack_texts(out_dir)
    conflict = [t for t in texts.values() if "Conflict Fictional Co" in t][0]
    coherent = [t for t in texts.values() if "Coherent Fictional Co" in t][0]
    assert "Data conflict to check" in conflict, conflict
    assert "has_website is no but website_status is live" in conflict
    assert "Data conflict to check" not in coherent, coherent


def test_rerun_single_pack_still_overwrites_same_file(tmp_path):
    proc, store = import_leads(tmp_path, "scoring_leads.csv")
    assert proc.returncode == 0, out_text(proc)
    out_dir = Path(tmp_path) / "packs"
    assert pack(store, out_dir).returncode == 0
    first = pack_texts(out_dir)
    assert pack(store, out_dir).returncode == 0
    second = pack_texts(out_dir)
    assert list(first) == list(second) == ["hilltop-quarry-hauling-pitch-pack.md"]
