"""TF-IDF task recall with rule pinning and superseded handling."""
from __future__ import annotations
import math, re
from collections import Counter, defaultdict

from .conflicts import detect_contradictions
from .tokens import estimate

_WORD = re.compile(r"[a-z0-9_]+")

def _terms(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())

def tfidf_rank(items, task: str) -> list[tuple[object, float]]:
    """Rank *items* against *task* by TF-IDF over title + text.

    Returns ``(item, score)`` pairs, best first, ties broken by item
    id so the order is deterministic. Keyword matching only: a
    paraphrase with no shared words scores 0.
    """
    docs = [_terms(it.title + " " + it.text) for it in items]
    n = len(docs)
    df: Counter = Counter()
    for d in docs:
        df.update(set(d))
    q = Counter(_terms(task))
    scored = []
    for it, d in zip(items, docs):
        if not d:
            scored.append((it, 0.0)); continue
        tf = Counter(d)
        score = 0.0
        for term, qc in q.items():
            if term in tf:
                idf = math.log((n + 1) / (df[term] + 1)) + 1.0
                score += qc * (tf[term] / len(d)) * idf
        scored.append((it, round(score, 6)))
    scored.sort(key=lambda pair: (-pair[1], pair[0].id))
    return scored

_NONE_REFS = {"", "none", "no", "n/a", "na", "null", "nil", "-", "nothing"}

def _real_supersedes(item) -> str | None:
    """The item's Supersedes target, or None.

    A raw value of 'none' is NOT a supersession: returning it as a
    truthy string produced spurious supersedes-in-bundle conflicts
    for every decision that superseded nothing (REPORT_B F1b).
    """
    v = getattr(item, "supersedes", None)
    if v is None:
        return None
    v = str(v).strip().strip('"').strip()
    return None if v.lower() in _NONE_REFS else v

def is_pinned(item, profile: dict) -> bool:
    """True when *item* is a standing rule: a decision tagged rule /
    pinned / standing, or an item whose title or id is listed in the
    profile's ``pinned_rules``. Note select() checks supersession
    before pinning, so a superseded rule is never pinned into a
    selection even when this returns True for it."""
    if item.source_type == "decision" and any(
            t in item.tags for t in ("rule", "pinned", "standing-rule", "standing")):
        return True
    pins = [str(p).lower() for p in profile.get("pinned_rules", [])]
    return item.title.lower() in pins or item.id.lower() in pins

def select(items, task: str = "", profile: dict | None = None,
           max_items: int | None = None, mode: str | None = None):
    """Return (selected, not_selected, conflicts).

    selected: list of dicts {item, score, pinned, mode}
    Superseded decisions are NEVER selected and NEVER pinned:
    supersession beats rule pinning (tags and profile pinned_rules
    alike) unconditionally. They go to not_selected with reason
    superseded, so bundle export records them only as
    excluded/superseded in the manifest (REPORT_B F1).
    The same precedence applies to secret-blocked items: a finding
    blocks the item even when it is a pinned standing rule, so no
    selected item ever carries secret text to a preview surface.
    A conflict is recorded when a selected decision supersedes one that
    is also in the corpus (the older text is flagged, not hidden).
    """
    profile = profile or {}
    limit = max_items if max_items is not None else int(profile.get("max_items", 50))
    if limit < 1:
        # Callers that bypass load_profile validation must not get
        # silent nonsense from a zero/negative limit either.
        raise ValueError(f"max_items must be >= 1, got {limit!r}")
    ranked = tfidf_rank(items, task) if task else [(it, 0.0) for it in items]
    score_of = {id(it): s for it, s in ranked}
    selected, not_selected, conflicts = [], [], []
    # recent mode: restrict ranked pool to last N by date first
    pool = list(items)
    if mode == "recent":
        n = int(profile.get("recent_n", 5))
        if n < 1:
            # dated[:-1] would silently drop the oldest item instead
            # of meaning "last -1"; reject it like the profile does.
            raise ValueError(f"recent_n must be >= 1, got {n!r}")
        dated = sorted([i for i in pool if i.date], key=lambda i: i.date, reverse=True)
        pool = dated[:n] + [i for i in pool if not i.date][:0]
    selected_ids = set()
    for it in pool:
        if it.status == "superseded":
            # Supersession first, before any pinning is even computed:
            # a superseded standing rule is still superseded.
            not_selected.append({"item": it, "reason": "superseded",
                                 "superseded_by": it.superseded_by})
            continue
        if it.blocked:
            # Secrets block BEFORE pinning too: a pinned rule carrying
            # a secret finding must never be selected, or its text
            # leaks through surfaces that preview selected items
            # (MCP recall_search text_preview, dashboard, bundle).
            not_selected.append({"item": it, "reason": "secret-finding (blocked)",
                                 "findings": it.secret_findings})
            continue
        pinned = is_pinned(it, profile)
        entry = {"item": it, "score": score_of.get(id(it), 0.0), "pinned": pinned}
        if pinned:
            selected.append(entry); selected_ids.add(it.id)
    rest = [it for it, _s in ranked if it in pool and it.id not in selected_ids
            and it.status != "superseded" and not it.blocked]
    blocked_seen = {e["item"].id for e in not_selected}
    for it in pool:
        if it.blocked and it.id not in blocked_seen:
            blocked_seen.add(it.id)
            not_selected.append({"item": it, "reason": "secret-finding (blocked)",
                                 "findings": it.secret_findings})
    if task:
        rest = [it for it in rest if score_of.get(id(it), 0.0) > 0]
    for it in rest:
        if len([s for s in selected if not s["pinned"]]) + len([s for s in selected if s["pinned"]]) >= limit and not is_pinned(it, profile):
            not_selected.append({"item": it, "reason": "over max_items"})
            continue
        selected.append({"item": it, "score": score_of.get(id(it), 0.0), "pinned": False})
        selected_ids.add(it.id)
    # anything in pool never touched -> not selected with reason
    seen = selected_ids | {e["item"].id for e in not_selected}
    for it in pool:
        if it.id not in seen:
            not_selected.append({"item": it, "reason": "not ranked for task" if task else "not selected"})
    for entry in selected:
        it = entry["item"]
        sup = _real_supersedes(it)
        if sup:
            conflicts.append({
                "type": "supersedes-in-bundle",
                "current": it.title, "superseded": sup,
                "note": "older decision is flagged superseded and excluded from current context",
            })
        # No pinned-superseded conflict branch: superseded items are
        # never in `selected` any more (see the pool loop above).
    # Unresolved contradictions between the active decisions that ARE
    # being served: flagged alongside the supersedes conflicts, never
    # resolved here - both decisions stay selected (conflicts.py).
    conflicts.extend(detect_contradictions(
        e["item"] for e in selected))
    # order: pinned first, then score desc
    selected.sort(key=lambda e: (not e["pinned"], -e["score"], e["item"].id))
    for e in selected:
        e["tokens"] = estimate(e["item"].text)
    return selected, not_selected, conflicts

def explain(items, task: str, item_key: str, profile: dict | None = None) -> dict:
    """Explain one item for *task* as a JSON-friendly dict.

    *item_key* matches an item id, exact title, or source path. The
    result says whether the item was selected and why (pinned rule,
    ranked, superseded, blocked, not ranked, ...), or that no such
    item exists in the project sources.
    """
    selected, not_selected, _c = select(items, task, profile or {})
    for coll, was in ((selected, True),):
        for e in coll:
            if item_key in (e["item"].id, e["item"].title, e["item"].provenance.path):
                return {"item": e["item"].to_dict(include_text=False), "selected": was,
                        "score": e["score"], "pinned": e["pinned"],
                        "tokens_estimate": e.get("tokens", estimate(e["item"].text)),
                        "reason": "pinned rule" if e["pinned"] else "ranked for task"}
    for e in not_selected:
        it = e["item"]
        if item_key in (it.id, it.title, it.provenance.path):
            return {"item": it.to_dict(include_text=False), "selected": False,
                    "reason": e["reason"]}
    return {"item": None, "selected": False, "reason": "no such item in project sources"}
