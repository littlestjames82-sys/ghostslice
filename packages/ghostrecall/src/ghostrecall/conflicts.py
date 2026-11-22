"""Unresolved-contradiction detection between active decisions.

PLAN.md / README.md promise: "If a source contradicts a newer
decision in the same bundle, Recall flags the conflict rather than
picking a winner." Until now only an explicit ``Supersedes:`` link
produced a conflict. Two *active* decisions that say opposite things
about the same topic - with no supersedes link between them - were
both served silently as current. That is exactly the stale-memory
failure mode Recall exists to surface.

This module detects that case deterministically and extractively:

* Scope: decision items only, active status only. Superseded items
  never reach selection, so a resolved reversal is not re-flagged.
* Topic overlap: the two decision lines must share at least two
  content terms (stopwords removed, light stemming for comparison
  only), so unrelated decisions are never paired.
* Opposition, either signal is enough once overlap holds:
  1. negation flip - one decision negates a term the other asserts
     positively (a negator scopes over the next three tokens), or
  2. an explicit opposite-directive pair (enable/disable,
     allow/forbid, ...) asserted by the two decisions about shared
     terms.
* A hit is a FLAG, never a resolution: both decisions stay selected,
  nothing is dropped, re-ranked, or rewritten. The conflict record
  names both items, the shared terms, and the opposing terms so a
  human can see *why* it was flagged.

Stdlib only, no model, no network - same discipline as the rest of
the tool. Detection runs over the decision line (``Decision:`` text
when parsed, else the item text), not reasons: reasons routinely
mention the option that was rejected, which is not a contradiction.
"""
from __future__ import annotations
import re

_WORD = re.compile(r"[a-z0-9_']+")

STOPWORDS = {
    "a", "an", "the", "all", "any", "for", "of", "in", "on", "to",
    "and", "or", "with", "without", "once", "it", "its", "is", "are",
    "be", "been", "has", "have", "had", "this", "that", "every",
    "per", "at", "by", "from", "into", "as", "when", "until",
}

NEGATORS = {
    "never", "no", "not", "n't", "dont", "don't", "stop", "avoid",
    "ban", "banned", "prohibit", "prohibited", "prohibits",
    "reject", "rejected", "forbid", "forbidden", "drop", "remove",
    "removed", "disable", "disabled", "exclude", "excluded",
    "hold", "halt",
}

# Opposite directive stems: (side_a, side_b). Kept small and explicit
# so every flag can be explained by naming the pair that fired.
OPPOSITE_PAIRS = [
    ("enable", "disable"),
    ("allow", "forbid"),
    ("allow", "deny"),
    ("permit", "forbid"),
    ("include", "exclude"),
    ("start", "stop"),
    ("open", "close"),
    ("require", "optional"),
]

_NEGATION_WINDOW = 3


def _stem(word: str) -> str:
    """Comparison-only stem: consistent, not pretty."""
    w = word.lower().strip("'")
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 3 and w.endswith("es"):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def _tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _decision_line(item) -> str:
    dec = getattr(item, "decision_text", "") or ""
    if dec.strip():
        return dec
    for ln in (item.text or "").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            return re.sub(r"^(?:decision\s*:\s*)", "", ln, flags=re.I)
    return item.title or ""


class _Side:
    """One decision line, analysed for topic, negation, directives."""

    def __init__(self, item):
        self.item = item
        toks = _tokens(_decision_line(item))
        self.stems: dict[str, str] = {}       # stem -> original word
        self.positive: set[str] = set()       # content stems not negated
        self.negated: set[str] = set()        # content stems under negation
        neg_left = 0
        for tok in toks:
            stem = _stem(tok)
            if tok in NEGATORS or stem in {_stem(n) for n in NEGATORS}:
                neg_left = _NEGATION_WINDOW
                continue
            if tok in STOPWORDS or len(tok) < 3:
                if neg_left:
                    neg_left -= 1
                continue
            self.stems.setdefault(stem, tok)
            if neg_left:
                self.negated.add(stem)
                neg_left -= 1
            else:
                self.positive.add(stem)
        self.content = self.positive | self.negated


def detect_contradictions(items) -> list[dict]:
    """Flag contradictory pairs among active decision items.

    ``items`` is an iterable of model.Item-like objects. Returns one
    record per contradictory pair, in deterministic (id, id) order.
    Both items stay in the caller's selection: this only flags.
    """
    sides = [_Side(it) for it in items
             if getattr(it, "source_type", None) == "decision"
             and getattr(it, "status", "active") == "active"]
    sides.sort(key=lambda s: s.item.id)
    neg_stems = {_stem(n) for n in NEGATORS}
    opp = [(_stem(a), _stem(b)) for a, b in OPPOSITE_PAIRS]
    out: list[dict] = []
    for i, a in enumerate(sides):
        for b in sides[i + 1:]:
            if _supersedes_linked(a.item, b.item):
                continue  # an explicit link already flags this pair
            shared = a.content & b.content
            if len(shared) < 2:
                continue
            opposing: list[str] = []
            signal = None
            flip = (a.negated & b.positive) | (b.negated & a.positive)
            # A term that is merely *mentioned* under negation on one
            # side and asserted on the other is the core signal; the
            # negator stems themselves don't count as the flipped term.
            flip -= neg_stems
            if flip:
                signal = "negation"
                opposing = sorted(a.stems.get(s, s) for s in flip)
            else:
                for x, y in opp:
                    if (x in a.content and y in b.content) or \
                       (y in a.content and x in b.content):
                        signal = "opposite-directives"
                        opposing = sorted({s.stems[t] for s in (a, b)
                                           for t in (x, y) if t in s.stems})
                        break
            if not signal:
                continue
            shared_words = sorted(a.stems.get(s, s) for s in shared)
            out.append({
                "type": "possible-contradiction",
                "current": a.item.title,
                "other": b.item.title,
                "items": [a.item.id, b.item.id],
                "signal": signal,
                "shared_terms": shared_words,
                "opposing_terms": opposing,
                "note": ("two active decisions appear to contradict each "
                         "other; flagged, not resolved - both are served "
                         "and a human should settle which is current"),
            })
    return out


def _supersedes_linked(a, b) -> bool:
    for src, dst in ((a, b), (b, a)):
        ref = getattr(src, "supersedes", None)
        if ref and str(ref).strip().lower() in (
                dst.title.lower(), dst.id.lower()):
            return True
    return False
