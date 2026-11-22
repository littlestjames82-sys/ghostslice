"""Scoring: additive points, every point carries a reason.

Weights encode the Sep 25, 2026 prospects shape (see PLAN.md).
Unknown fields score zero. A score is a ranking aid, never a
judgement on the business.
"""
from __future__ import annotations

_STATUS_POINTS = {"dead": 20, "template": 15, "none": 10, "live": 0, "unknown": 0}
_STATUS_REASONS = {
    "dead": "website_status is dead (+20): a dead link is a concrete talking point",
    "template": "website_status is template only (+15): no dedicated website of its own",
    "none": "website_status is none (+10): no website found in the imported data",
}
_PROFILE_POINTS = {"unclaimed": 20, "none": 15, "listing-only": 10, "claimed": 0, "unknown": 0}
_PROFILE_REASONS = {
    "unclaimed": "google_profile is unclaimed (+20): profile not claimed in the imported data",
    "none": "google_profile is none (+15): no Google profile in the imported data",
    "listing-only": "google_profile is listing only (+10): directory listing, not a claimed profile",
}


def tier_for(score: int) -> int:
    """Map a score to its tier: 60+ is Tier 1, 40 to 59 Tier 2, else Tier 3."""
    if score >= 60:
        return 1
    if score >= 40:
        return 2
    return 3


def score_lead(lead) -> tuple:
    """Score one lead and update it in place.

    Returns ``(score, tier, reasons)``. Points are additive (see the
    table in README.md), capped at 100, and each contribution appends
    a human-readable reason, so a score is always explainable from
    its reasons. Unknown fields contribute zero and add no reason.
    """
    points = 0
    reasons = []

    if lead.has_website is False:
        points += 30
        reasons.append("no dedicated website (+30): has_website is false in the imported data")

    status_pts = _STATUS_POINTS.get(lead.website_status, 0)
    if status_pts:
        points += status_pts
        reasons.append(_STATUS_REASONS[lead.website_status])

    profile_pts = _PROFILE_POINTS.get(lead.google_profile, 0)
    if profile_pts:
        points += profile_pts
        reasons.append(_PROFILE_REASONS[lead.google_profile])

    if lead.rating is not None:
        if lead.rating < 3.8:
            points += 10
            reasons.append(f"rating {lead.rating:g} is below 3.8 (+10): reputation rebuild angle")
        elif lead.rating >= 4.5:
            points += 8
            reasons.append(f"rating {lead.rating:g} is 4.5 or above (+8): strong reviews to showcase")
        else:
            points += 3
            reasons.append(f"rating {lead.rating:g} is in the middle range (+3)")

    if lead.phone:
        points += 5
        reasons.append("phone on file (+5): reachable by phone")
    if lead.email:
        points += 5
        reasons.append("email on file (+5): reachable by email")

    score = min(points, 100)
    if score != points:
        reasons.append(f"score capped at 100 (raw points {points})")
    tier = tier_for(score)
    lead.score = score
    lead.tier = tier
    lead.reasons = reasons
    return score, tier, reasons


def unknowns(lead) -> list:
    """Names of fields that are unknown, for honest pack display."""
    out = []
    if not lead.trade:
        out.append("trade")
    if not lead.town:
        out.append("town")
    if not lead.phone:
        out.append("phone")
    if not lead.email:
        out.append("email")
    if lead.has_website is None:
        out.append("has_website")
    if lead.website_status == "unknown":
        out.append("website_status")
    if lead.google_profile == "unknown":
        out.append("google_profile")
    if lead.rating is None:
        out.append("rating")
    return out
