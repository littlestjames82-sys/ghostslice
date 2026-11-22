"""Local JSON store plus CSV/JSON import with dedupe.

The store is a single local file. No network is used anywhere in
this package: import reads only the file the user names.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Lead, fuzzy_name_match, normalise_name, normalise_town, phone_digits
from .scoring import score_lead

STORE_VERSION = 1


def load_store(path) -> list:
    """Load leads from the store file at ``path``.

    A missing file loads as an empty list. Stored records are
    validated on the way in (see ``Lead.from_dict``), so a corrupt
    or hand-edited value raises ValueError here rather than failing
    later inside scoring or pack generation.
    """
    p = Path(path)
    if not p.exists():
        return []
    # utf-8-sig, same as the import readers: a store hand-edited in a
    # Windows editor may carry a BOM and must still load.
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        if "leads" not in data:
            # Never treat a foreign or mistyped object as an empty
            # store: the next save would silently wipe the real one.
            raise ValueError("store object has no 'leads' list")
        rows = data["leads"]
    else:
        rows = data
    if not isinstance(rows, list):
        # Raise ValueError (which the CLI reports as a clean
        # cannot-read-store error), not the TypeError that iterating
        # an int or string mapping used to crash with.
        raise ValueError("store must be a JSON list, or an object with a leads list")
    return [Lead.from_dict(r) for r in rows]


def save_store(path, leads) -> None:
    """Write ``leads`` to the store file, creating parent folders.

    The on-disk shape is a JSON object with ``version``, ``tool``,
    and a ``leads`` list of plain lead records.
    """
    p = Path(path)
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": STORE_VERSION, "tool": "ghostleads",
               "leads": [lead.to_dict() for lead in leads]}
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_import_file(path) -> list:
    """Return a list of raw row dicts from a .csv or .json file."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".json":
        # utf-8-sig, same as the CSV reader: a BOM saved by a
        # spreadsheet or editor must not fail the whole import.
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            key = next((k for k in data
                        if isinstance(k, str) and k.strip().lower() == "leads"),
                       None)
            if key is None:
                # A single lead object, or a mistyped wrapper key,
                # used to import as a silent empty success.
                raise ValueError("JSON import object has no 'leads' list: "
                                 "use a list, or an object with a leads list")
            data = data[key]
        if not isinstance(data, list):
            raise ValueError("JSON import must be a list, or an object with a leads list")
        return data
    if suffix == ".csv":
        with p.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            try:
                rows = list(reader)
            except csv.Error as exc:
                # Malformed CSV (for example a field over the parser
                # limit) is a ValueError for the caller, not a raw
                # csv.Error traceback through the CLI.
                raise ValueError(f"could not parse CSV: {exc}") from exc
            fieldnames = [str(f).strip().lower()
                          for f in (reader.fieldnames or []) if f]
            if len(fieldnames) != len(set(fieldnames)):
                # DictReader silently keeps only the last duplicate
                # column, discarding the earlier column's data.
                raise ValueError("CSV header has duplicate column names")
            return rows
    raise ValueError(f"unsupported import format {suffix!r}: use .csv or .json")


def _field_agrees(x, y) -> bool:
    """True when both values are known and equal (case-insensitive)."""
    x = " ".join(str(x or "").lower().split())
    y = " ".join(str(y or "").lower().split())
    return bool(x) and x == y


def _attribute_agrees(a, b) -> bool:
    """True when a known business attribute agrees on both records.

    Only values that are actually known on both sides count: two
    blank ratings or two unknown statuses are the absence of
    evidence, not agreement."""
    if a.rating is not None and b.rating is not None:
        if a.rating == b.rating:
            return True
    if a.website_status != "unknown" and b.website_status != "unknown":
        if a.website_status == b.website_status:
            return True
    if a.google_profile != "unknown" and b.google_profile != "unknown":
        if a.google_profile == b.google_profile:
            return True
    return False


def same_lead(a, b) -> bool:
    """Dedupe predicate: are these two records the same business?

    Exact-name path: same normalised name, AND either:
    - both records carry a phone and the digits match, or
    - at least one record has no phone and the towns match.

    The old key-based version required a phone on BOTH records to
    use the phone branch, so a lead first imported phone-only and
    later re-imported with a phone (the common directory pattern)
    never merged and silently duplicated.

    Near-spelling path (fuzzy_name_match, e.g. Dautel vs Dautell):
    a mistyped name is weaker evidence than an exact one, so the
    corroboration bar is higher, never lower:
    - both phones present: they must match. Different phones never
      merge, on either path: they may be two branches, or an old
      and a new number, and only a human can tell which.
    - any phone missing: the towns must match and be known, AND
      either the emails agree, or the trades agree AND one known
      business attribute also agrees (rating, website_status, or
      google_profile). Town alone, or town plus a generic trade,
      never merges two differently spelled names, so two distinct
      same-town businesses with similar names stay apart. A sparse
      misspelled row that carries nothing else in common stays a
      separate lead: a missed merge is visible and fixable by hand,
      a wrong merge silently hides a lead.
    """
    name_a = normalise_name(a.name)
    if not name_a:
        return False
    exact = name_a == normalise_name(b.name)
    if not exact and not fuzzy_name_match(a.name, b.name):
        return False
    digits_a = phone_digits(a.phone)
    digits_b = phone_digits(b.phone)
    if digits_a and digits_b:
        return digits_a == digits_b
    town_a = normalise_town(a.town or "")
    town_b = normalise_town(b.town or "")
    if not exact:
        if not town_a or town_a != town_b:
            return False
        if _field_agrees(a.email, b.email):
            return True
        return _field_agrees(a.trade, b.trade) and _attribute_agrees(a, b)
    if digits_a or digits_b:
        # Exactly one record has a phone: the town has to match and
        # be known, or there is no evidence these are the same lead.
        return bool(town_a) and town_a == town_b
    # Neither record has a phone: towns must match, with two blank
    # towns counting as a match. A sparse lead (no phone, no town)
    # re-imported unchanged must not duplicate itself.
    return town_a == town_b


def merge_leads(existing: list, incoming: list) -> dict:
    """Merge incoming leads into existing (mutated), matched with
    same_lead in store order. First record wins; later records fill
    blanks only. Returns counts: added, merged, total."""
    added = 0
    merged = 0
    for lead in incoming:
        match = None
        for candidate in existing:
            if same_lead(candidate, lead):
                match = candidate
                break
        if match is not None:
            match.fill_blanks_from(lead)
            merged += 1
        else:
            existing.append(lead)
            added += 1
    return {"added": added, "merged": merged, "total": len(existing)}


def import_file(store_path, import_path) -> dict:
    """Import a CSV/JSON file into the store. Returns a report dict
    with added / merged / skipped (each skip has where + why)."""
    rows = read_import_file(import_path)
    leads = load_store(store_path)
    incoming = []
    skipped = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            skipped.append({"where": f"row {idx + 1}", "why": "not an object"})
            continue
        try:
            incoming.append(Lead.from_row(row))
        except ValueError as exc:
            skipped.append({"where": f"row {idx + 1}", "why": str(exc)})
    counts = merge_leads(leads, incoming)
    for lead in leads:
        score_lead(lead)
    leads.sort(key=lambda l: (-l.score, l.name.lower()))
    save_store(store_path, leads)
    return {**counts, "skipped": skipped, "imported_rows": len(rows)}
