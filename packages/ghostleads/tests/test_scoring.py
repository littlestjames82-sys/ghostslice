"""PLAN verification bars 1 and 2: scoring and honesty.

Expected scores from the PLAN table (capped at 100):
  Hilltop Quarry Hauling   30+20+20+10+5      = 85  Tier 1
  Cedar Sign Works         30+15+10+8+5       = 68  Tier 1
  Riverbend Fictional HVAC 30+10+0+3+5        = 48  Tier 2
  Maple Street Bakery      0+0+0+3+5+5        = 13  Tier 3
  Mystery Works            all unknown        = 0   Tier 3

Unknown is never scored as a gap: Mystery Works has no website field
at all, so it must not collect the no-website points.
"""
from conftest import find_record, import_leads, out_text, score_records


def _scored(tmp_path):
    proc, store = import_leads(tmp_path, "scoring_leads.csv")
    assert proc.returncode == 0, out_text(proc)
    return score_records(store)


def _score(rec):
    val = rec.get("score")
    assert val is not None, f"record has no score: {rec}"
    return float(val)


def _tier(rec):
    val = rec.get("tier")
    assert val is not None, f"record has no tier: {rec}"
    # Accept 1, "1", "Tier 1", "tier-1" shapes.
    text = str(val).lower()
    for n in ("1", "2", "3"):
        if n in text:
            return int(n)
    raise AssertionError(f"unreadable tier {val!r}")


def _reasons_text(rec):
    reasons = rec.get("reasons") or rec.get("score_reasons") or []
    if isinstance(reasons, list):
        parts = []
        for r in reasons:
            parts.append(str(r.get("reason", r) if isinstance(r, dict)
                             else r))
        return " ".join(parts).lower()
    return str(reasons).lower()


def test_no_website_dead_unclaimed_scores_tier_1_with_reasons(tmp_path):
    records = _scored(tmp_path)
    hill = find_record(records, "Hilltop Quarry")
    assert _score(hill) == 85, hill
    assert _tier(hill) == 1
    reasons = _reasons_text(hill)
    assert reasons, "Tier 1 verdict carries no reasons"
    assert "website" in reasons
    assert any(tok in reasons for tok in ("dead", "unclaimed"))


def test_live_claimed_mid_rating_scores_tier_3(tmp_path):
    records = _scored(tmp_path)
    maple = find_record(records, "Maple Street")
    assert _score(maple) == 13, maple
    assert _tier(maple) == 3


def test_all_unknown_scores_only_on_what_is_known(tmp_path):
    records = _scored(tmp_path)
    mystery = find_record(records, "Mystery Works")
    assert _score(mystery) == 0, (
        f"unknown fields were scored as gaps: {mystery}")
    assert _tier(mystery) == 3


def test_template_and_showcase_rating_land_tier_1(tmp_path):
    records = _scored(tmp_path)
    cedar = find_record(records, "Cedar Sign")
    assert _score(cedar) == 68, cedar
    assert _tier(cedar) == 1
    assert "showcase" in _reasons_text(cedar) or \
        "4.5" in _reasons_text(cedar) or \
        "strong" in _reasons_text(cedar) or \
        "rating" in _reasons_text(cedar)


def test_mid_tier_and_ranking_order(tmp_path):
    records = _scored(tmp_path)
    river = find_record(records, "Riverbend")
    assert _score(river) == 48, river
    assert _tier(river) == 2
    scores = [_score(r) for r in records]
    assert scores == sorted(scores, reverse=True), (
        f"score output is not ranked descending: {scores}")
    assert all(0 <= s <= 100 for s in scores), "score outside 0 to 100"


def test_csv_and_json_imports_score_the_same(tmp_path):
    csv_dir = tmp_path / "csvrun"
    json_dir = tmp_path / "jsonrun"
    csv_dir.mkdir(); json_dir.mkdir()
    proc_c, store_c = import_leads(csv_dir, "scoring_leads.csv")
    proc_j, store_j = import_leads(json_dir, "leads.json")
    assert proc_c.returncode == 0, out_text(proc_c)
    assert proc_j.returncode == 0, out_text(proc_j)
    from conftest import score_records as _sr
    hill_c = find_record(_sr(store_c), "Hilltop Quarry")
    hill_j = find_record(_sr(store_j), "Hilltop Quarry")
    assert _score(hill_c) == _score(hill_j) == 85
