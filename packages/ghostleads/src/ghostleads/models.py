"""Lead model, field normalisation, and dedupe keys.

Fields mirror the Sep 25, 2026 East TN prospects file. Every field
except name is optional: blank means unknown, and unknown is never
treated as a known gap or filled with a guess.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

WEBSITE_STATUSES = ("live", "dead", "template", "none", "unknown")
GOOGLE_PROFILES = ("claimed", "unclaimed", "listing-only", "none", "unknown")

_TRUE = {"true", "yes", "y", "1", "t"}
_FALSE = {"false", "no", "n", "0", "f"}


def _clean(value) -> str:
    """Return ``value`` as a single-line string (``""`` for ``None``).

    Every imported text field passes through here, so the rest of
    the package can assume single-line values with single spaces.
    """
    if value is None:
        return ""
    if isinstance(value, (list, dict, tuple, set)):
        # A nested JSON value is never a single-line field: stringifying
        # it would store a Python repr (for example "['Foo', 'Bar']")
        # as a business name or phone and print it in a pack as if it
        # were researched data. Reject it so the row is skipped (or a
        # corrupt store fails cleanly) instead.
        raise ValueError(f"field value is not a single value: {value!r}")
    # Drop C0/DEL control characters other than whitespace (a NUL byte
    # in a CSV cell otherwise survives into the store and the pack).
    s = re.sub(r"[\x00-\x08\x0e-\x1f\x7f]", "", str(value))
    # Collapse every whitespace run, newlines included: imported
    # fields are single-line values, and a quoted CSV newline must
    # not be able to inject lines (for example fake markdown
    # headings) into a generated pack.
    return " ".join(s.split())


def _fold_ascii(s: str) -> str:
    """Fold accented letters to their ASCII base (é -> e, ñ -> n) so
    directory spelling variants of the same name or town line up."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def parse_bool(value):
    """Return True/False, or None for blank/unknown/unrecognised."""
    if isinstance(value, bool):
        return value
    s = _clean(value).lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return None


def parse_rating(value):
    """Return a float in [0, 5], None for blank. Raise ValueError if invalid."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        # JSON true/false is not a rating; float(True) would silently
        # store 1.0, an invented low rating.
        raise ValueError(f"rating is not a number: {value!r}")
    try:
        rating = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"rating is not a number: {value!r}")
    if not 0.0 <= rating <= 5.0:
        raise ValueError(f"rating out of range 0-5: {value!r}")
    return rating


def normalise_website_status(value) -> str:
    """Normalise a website_status value to a member of WEBSITE_STATUSES.

    Accepts the documented values plus common source spellings
    (``404`` for dead, ``business.site`` for template, and similar).
    Blank means ``"unknown"``. Any other value raises ValueError so
    the row is skipped with a reason instead of scored silently.
    """
    s = _clean(value).lower().replace("_", "-").replace(" ", "-")
    if not s:
        return "unknown"
    if s in ("dead", "404", "dead-404", "gone", "retired"):
        return "dead"
    if s in ("template", "business.site", "business-site", "google-site", "google-template"):
        return "template"
    if s in ("live", "real", "dedicated", "active"):
        return "live"
    if s in ("none", "no", "missing", "facebook-only", "directory-only", "directories-only"):
        return "none"
    if s == "unknown":
        return "unknown"
    raise ValueError(f"unknown website_status: {value!r} "
                     f"(expected one of {', '.join(WEBSITE_STATUSES)}, dead, or template)")


def normalise_google_profile(value) -> str:
    """Normalise a google_profile value to a member of GOOGLE_PROFILES.

    Accepts the documented values plus common aliases (``gbp`` for
    listing-only, ``verified`` for claimed, and similar). Blank
    means ``"unknown"``. Any other value raises ValueError.
    """
    s = _clean(value).lower().replace("_", "-").replace(" ", "-")
    if not s:
        return "unknown"
    if s in ("listing", "listing-only", "directory", "directory-only", "directories-only",
             "google-listing", "gbp", "google-business-profile"):
        return "listing-only"
    if s in ("claimed", "verified"):
        return "claimed"
    if s in ("unclaimed", "not-claimed"):
        return "unclaimed"
    if s in ("none", "no", "missing"):
        return "none"
    if s == "unknown":
        return "unknown"
    raise ValueError(f"unknown google_profile: {value!r} "
                     f"(expected one of {', '.join(GOOGLE_PROFILES)})")


def phone_digits(value) -> str:
    """Return only the digits of a phone value, for dedupe comparison.

    Formatting is ignored, a trailing extension (``ext. 12`` / ``x12``)
    is stripped, and a leading US country code ``1`` on an
    11-digit number is stripped, so differently formatted listings
    of the same number compare equal. Blank input returns ``""``.
    """
    s = _clean(value).lower()
    # A trailing extension ("423-555-0100 ext. 12", "... x12") is
    # switchboard routing, not part of the number: the same line
    # listed with and without one must dedupe together.
    s = re.sub(r"(?:ext\.?|extension|x)\s*\d+\s*$", "", s)
    digits = re.sub(r"\D", "", s)
    # Directory listings often carry the US country code: 1-865-555-0100
    # and (865) 555-0100 are the same number and must dedupe together.
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def normalise_name(value) -> str:
    """Return a comparison form of a business name for dedupe.

    Lowercases, folds accented letters to ASCII, reads ``&`` as
    "and", drops apostrophes and other punctuation, and strips
    common suffix words (llc, inc, co, the), so directory spelling
    variants of one business compare equal. This function itself is
    not fuzzy: a one-letter spelling difference still produces a
    different name here; near-spelling matching lives in
    ``fuzzy_name_match`` and merges only with corroboration in
    ``store.same_lead``.
    """
    s = _fold_ascii(_clean(value).lower())
    # "&" and "and" are the same word in directory variants
    # (C & C Ready Mix vs C and C Ready Mix), and an apostrophe is
    # not a letter boundary (Buck's vs Bucks).
    s = s.replace("&", " and ")
    s = re.sub(r"['\u2019`]", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(llc|inc|co|company|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalise_town(value) -> str:
    """Comparison key for towns: case, accents, and punctuation are
    directory formatting ("Exampleton," vs "Exampleton",
    "St. Marys" vs "St Marys"), not different places."""
    s = _fold_ascii(_clean(value).lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance between two strings.

    Levenshtein distance plus one extra edit: swapping two adjacent
    characters costs 1, so a transposed-letter typo ("Johnosn" for
    "Johnson") counts as a single slip, not two. Pure stdlib DP over
    the two words; lead names are short, so no bounding is needed.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev2 = None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1,          # deletion
                         cur[j - 1] + 1,      # insertion
                         prev[j - 1] + cost)  # substitution / match
            if prev2 is not None and j > 1 \
                    and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)  # transposition
        prev2, prev = prev, cur
    return prev[len(b)]


def fuzzy_name_match(a, b) -> bool:
    """True when two names are near-spelling variants, not identical.

    Directory listings mistype the same business ("Dautel" in one,
    "Dautell" in another, the standing example in PLAN.md), and the
    exact normalised match misses those. This predicate is kept
    deliberately narrow so it cannot swallow distinct businesses:

    - both names must normalise to the same number of words;
    - exactly one word may differ, and it must keep its first letter;
    - the differing word must be at least 4 letters long, and within
      edit distance 1, or distance 2 when the shorter word has at
      least 7 letters (room for two slips in a long name only);
    - identical normalised names return False: that is the exact
      match, handled by the caller with its own, looser rules.

    A True result is only ever a *candidate* match. store.same_lead
    additionally requires corroboration from other known fields
    before two records actually merge.
    """
    tokens_a = normalise_name(a).split()
    tokens_b = normalise_name(b).split()
    if not tokens_a or len(tokens_a) != len(tokens_b):
        return False
    differing = [(x, y) for x, y in zip(tokens_a, tokens_b) if x != y]
    if len(differing) != 1:
        return False
    x, y = differing[0]
    if x[0] != y[0] or min(len(x), len(y)) < 4:
        return False
    limit = 2 if min(len(x), len(y)) >= 7 else 1
    return edit_distance(x, y) <= limit


@dataclass
class Lead:
    """One stored lead: imported fields plus its score state.

    Only ``name`` is required. Every other field defaults to blank
    or unknown (``has_website`` and ``rating`` default to ``None``),
    and unknown is a real state throughout the tool: it scores zero,
    shows as ``(blank)`` in a pack, and is never filled with a guess.
    ``score``, ``tier``, and ``reasons`` are written by the scorer.
    """

    name: str
    trade: str = ""
    town: str = ""
    phone: str = ""
    email: str = ""
    has_website: object = None  # True / False / None (unknown)
    website_status: str = "unknown"
    google_profile: str = "unknown"
    rating: object = None  # float or None
    notes: str = ""
    source: str = ""
    score: int = 0
    tier: int = 3
    reasons: list = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict) -> "Lead":
        """Build a Lead from a CSV/JSON row. Keys are case-insensitive."""
        low = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
        name = _clean(low.get("name") or low.get("business") or low.get("business_name"))
        if not name:
            raise ValueError("row has no name")
        lead = cls(
            name=name,
            trade=_clean(low.get("trade") or low.get("type") or low.get("category")),
            town=_clean(low.get("town") or low.get("city") or low.get("location")),
            phone=_clean(low.get("phone")),
            email=_clean(low.get("email")),
            has_website=parse_bool(low.get("has_website", low.get("has website"))),
            website_status=normalise_website_status(low.get("website_status", "")),
            google_profile=normalise_google_profile(low.get("google_profile", "")),
            rating=parse_rating(low.get("rating")),
            notes=_clean(low.get("notes") or low.get("angle")),
            source=_clean(low.get("source")),
        )
        # Consistency: explicit has_website False + unknown status is
        # scored as status none only via has_website; do not invent a
        # status. True + unknown stays unknown.
        return lead

    def dedupe_key(self) -> tuple:
        """Return this lead's simple (name, phone-or-town) key.

        Kept for compatibility and inspection. Actual import merging
        uses ``store.same_lead``, whose predicate also covers the
        mixed case where only one of two records carries a phone.
        """
        name = normalise_name(self.name)
        digits = phone_digits(self.phone)
        if digits:
            return (name, digits)
        return (name, normalise_town(self.town))

    def fill_blanks_from(self, other: "Lead") -> bool:
        """Fill blank/unknown fields from other. Never overwrite a
        known non-blank value. Returns True if anything changed."""
        changed = False
        for attr in ("trade", "town", "phone", "email", "notes", "source"):
            if not getattr(self, attr) and getattr(other, attr):
                setattr(self, attr, getattr(other, attr))
                changed = True
        if self.has_website is None and other.has_website is not None:
            self.has_website = other.has_website
            changed = True
        if self.website_status == "unknown" and other.website_status != "unknown":
            self.website_status = other.website_status
            changed = True
        if self.google_profile == "unknown" and other.google_profile != "unknown":
            self.google_profile = other.google_profile
            changed = True
        if self.rating is None and other.rating is not None:
            self.rating = other.rating
            changed = True
        return changed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Lead":
        """Rebuild a Lead from a stored record, with validation.

        The store is a plain JSON file a human can hand-edit, so its
        values get the same checks as an import row. A bad stored
        value raises ValueError here (the CLI reports it as a clean
        cannot-read-store error) instead of crashing later inside
        scoring or pack generation."""
        if not isinstance(data, dict):
            raise ValueError("stored lead is not an object")
        known = {f for f in cls.__dataclass_fields__}
        out = {k: v for k, v in data.items() if k in known}
        name = _clean(out.get("name"))
        if not name:
            raise ValueError("stored lead has no name")
        out["name"] = name
        for attr in ("trade", "town", "phone", "email", "notes", "source"):
            if attr in out:
                out[attr] = _clean(out[attr])
        if "has_website" in out and out["has_website"] is not None \
                and not isinstance(out["has_website"], bool):
            out["has_website"] = parse_bool(out["has_website"])
        if "website_status" in out:
            out["website_status"] = normalise_website_status(out["website_status"])
        if "google_profile" in out:
            out["google_profile"] = normalise_google_profile(out["google_profile"])
        if "rating" in out:
            out["rating"] = parse_rating(out["rating"])
        for attr in ("score", "tier"):
            if attr in out:
                if isinstance(out[attr], bool):
                    # JSON true/false is not a score: int(True) would
                    # silently store score 1 / tier 0 (an invalid tier).
                    out[attr] = 0 if attr == "score" else 3
                    continue
                try:
                    out[attr] = int(out[attr])
                except (TypeError, ValueError):
                    out[attr] = 0 if attr == "score" else 3
        if "reasons" in out:
            if not isinstance(out["reasons"], list):
                out["reasons"] = []
            else:
                # Reasons are printed verbatim in packs: keep them
                # single-line plain text, never raw stored objects.
                out["reasons"] = [_clean(str(r)) for r in out["reasons"]]
        return cls(**out)
