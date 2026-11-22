"""Draft pitch pack generation.

Hard rules (PLAN.md):
- No em dash character anywhere in a generated pack.
- No business detail appears unless it is in the stored record.
  Unknown fields are shown blank and their angles are omitted.
- Drafts only. There is deliberately no send function in this
  package, and every pack says so.
"""
from __future__ import annotations

import re
from pathlib import Path

from .scoring import unknowns

EM_DASH = "\u2014"  # em dash, escaped so the literal never sits in template copy
STUDIO = "Ghost Developer Studio"
STUDIO_CONTACT = "(423) 408-2150"  # Ryan's public TextNow number, studio contact only


def slugify(name: str) -> str:
    """Return a file-safe slug for a business name.

    Example: ``"Hilltop Quarry Hauling"`` becomes
    ``"hilltop-quarry-hauling"``. Used for pack file names and for
    matching ``pack --lead`` against a typed slug. An all-punctuation
    name falls back to ``"lead"``.
    """
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "lead"


def _blank(value) -> str:
    """Known value as text, or a blank marker. Never a guess."""
    if value is None or value == "" or value == "unknown":
        return "(blank)"
    return str(value)


def _angle_lines(lead) -> list:
    """Suggested angles built only from scored, known facts."""
    lines = []
    if lead.has_website is False:
        lines.append("Lead with the free custom website concept: this business has no dedicated website in the imported data, so a real site with services and a quote request form is the offer.")
    if lead.website_status == "dead":
        lines.append("Name the dead website link: anyone who finds the old page today hits a dead end. A working site fixes that first impression.")
    elif lead.website_status == "template":
        lines.append("Name the template page: a template listing is not a site the business controls. A dedicated site gives it a home it owns.")
    if lead.google_profile == "unclaimed":
        lines.append("Offer to help claim and clean up the unclaimed profile as part of the site work.")
    if lead.rating is not None and lead.rating < 3.8:
        lines.append(f"The imported rating is {lead.rating:g}. Frame the site as a reputation rebuild: best reviews up front, clear services, easy contact.")
    elif lead.rating is not None and lead.rating >= 4.5:
        lines.append(f"The imported rating is {lead.rating:g}. Those reviews are proof worth showcasing on a real homepage.")
    if not lines:
        lines.append("(blank) No angle is stated, because the stored record does not support one. Add verified notes first.")
    return lines


def _draft_pitch(lead) -> list:
    """Short outreach draft using only known fields."""
    who = lead.name
    if lead.trade and lead.town:
        noticed_subject = f"{who}, a {lead.trade} business in {lead.town}"
    elif lead.town:
        noticed_subject = f"{who} in {lead.town}"
    elif lead.trade:
        noticed_subject = f"{who}, a {lead.trade} business"
    else:
        noticed_subject = who

    facts = []
    if lead.has_website is False:
        facts.append("I could not find a dedicated website for the business")
    if lead.website_status == "dead":
        facts.append("the website link on file comes up dead")
    elif lead.website_status == "template":
        facts.append("the only web page I found is a template listing")
    if lead.google_profile == "unclaimed":
        facts.append("the Google profile looks unclaimed")

    lines = []
    lines.append(f"Hi, this is Ryan Cotten with {STUDIO} here in Oakdale, Tennessee.")
    lines.append("")
    if facts:
        lines.append(f"I was looking at {noticed_subject}, and " + ", and ".join(facts) + ".")
    else:
        lines.append(f"I was looking at {noticed_subject}.")
    lines.append("")
    lines.append("I build custom websites for local businesses, and I would like to put together a free website concept for you to look at. No cost and no obligation. If you like it, we can talk about making it live. If not, you have lost nothing.")
    lines.append("")
    lines.append("The concept would cover your services, your service area, photos of your work if you have them, and a simple quote request form so customers can reach you from their phones.")
    lines.append("")
    lines.append(f"If that sounds worth a look, call or text me at {STUDIO_CONTACT} and I will send the concept over.")
    lines.append("")
    lines.append("Thanks for your time,")
    lines.append("Ryan Cotten")
    lines.append(STUDIO)
    return lines


def build_pack(lead) -> str:
    """Return the full markdown pack for one lead.

    Section order is fixed: draft banner, lead snapshot, score with
    reasons, suggested angle, draft pitch, verification checklist,
    and a closing draft-only line. See the README section "What is
    in a pack" for what a reader should expect in each section.
    """
    rating_text = "(blank)" if lead.rating is None else f"{lead.rating:g}"
    website_text = "(blank)" if lead.has_website is None else ("yes" if lead.has_website else "no")
    lines = []
    lines.append(f"# Pitch Pack (Draft) - {lead.name}")
    lines.append("")
    lines.append("DRAFT ONLY. Not sent. Sending is Ryan's manual step, after re-verification.")
    lines.append("")
    lines.append("## Lead snapshot (as imported, blank means unknown)")
    lines.append("")
    lines.append(f"- Name: {_blank(lead.name)}")
    lines.append(f"- Trade: {_blank(lead.trade)}")
    lines.append(f"- Town: {_blank(lead.town)}")
    lines.append(f"- Phone: {_blank(lead.phone)}")
    lines.append(f"- Email: {_blank(lead.email)}")
    lines.append(f"- Has website: {website_text}")
    lines.append(f"- Website status: {_blank(lead.website_status)}")
    lines.append(f"- Google profile: {_blank(lead.google_profile)}")
    lines.append(f"- Rating: {rating_text}")
    if lead.notes:
        lines.append(f"- Notes (as imported): {lead.notes}")
    if lead.source:
        lines.append(f"- Source (as imported): {lead.source}")
    missing = unknowns(lead)
    if missing:
        lines.append(f"- Unknown fields: {', '.join(missing)}")
    conflicts = []
    if lead.has_website is True and lead.website_status == "none":
        conflicts.append("has_website is yes but website_status is none")
    if lead.has_website is False and lead.website_status == "live":
        conflicts.append("has_website is no but website_status is live")
    for conflict in conflicts:
        lines.append(f"- Data conflict to check: {conflict}. "
                     "Re-verify both fields before pitching.")
    lines.append("")
    lines.append("## Score")
    lines.append("")
    lines.append(f"- Score: {lead.score} / 100")
    lines.append(f"- Tier: {lead.tier}")
    if lead.reasons:
        for reason in lead.reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- No score reasons recorded. Run: ghostleads score")
    lines.append("")
    lines.append("Re-verify before pitching: imported data goes stale. A business may have closed, launched a site, or changed its phone since the import.")
    lines.append("")
    lines.append("## Suggested angle")
    lines.append("")
    for angle in _angle_lines(lead):
        lines.append(f"- {angle}")
    lines.append("")
    lines.append("## Draft pitch")
    lines.append("")
    lines.extend(_draft_pitch(lead))
    lines.append("")
    lines.append("## Verification checklist (before any manual send)")
    lines.append("")
    lines.append("- [ ] Business is still operating")
    lines.append("- [ ] Website status above still matches what a customer would find today")
    lines.append("- [ ] Phone (and email, if used) still match a public listing")
    lines.append("- [ ] Every detail in the draft above matches the verified business, with no blanks sent as-is")
    lines.append("- [ ] Ryan has read and approved this exact draft")
    lines.append("")
    lines.append("DRAFT ONLY. Not sent. GhostLeads has no send function by design.")
    text = "\n".join(lines) + "\n"
    if EM_DASH in text:  # defence in depth: template copy must never contain one
        text = text.replace(EM_DASH, "-")
    return text


def write_packs(leads, out_dir) -> list:
    """Write one pack per lead. Returns the list of Paths written.

    Two different leads can slug to the same file name ("Cedar
    Signs!" and "Cedar Signs"). Within one run, a colliding lead
    gets a -2, -3 suffix instead of silently overwriting the pack
    written just before it. Re-running a single lead still
    overwrites its own pack, as the plan states."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    used = set()
    for lead in leads:
        base = slugify(lead.name)
        filename = f"{base}-pitch-pack.md"
        n = 2
        while filename in used:
            filename = f"{base}-{n}-pitch-pack.md"
            n += 1
        used.add(filename)
        path = out / filename
        path.write_text(build_pack(lead), encoding="utf-8")
        written.append(path)
    return written
