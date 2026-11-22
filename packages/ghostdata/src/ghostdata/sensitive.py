"""Sensitive column detection: by name and by value shape.

A column is redacted when its name matches a sensitive pattern, or when
enough of its values match a sensitive shape (email, phone, payment
card with a Luhn check, SSN). Shape checks run on string values, and
on native JSON integers for the card shape only. Detection stores
counters only, never the values themselves.
"""
from __future__ import annotations

import re

NAME_PATTERNS = [
    (re.compile(r"pass(word|wd|phrase)?", re.I), "column name matches password"),
    (re.compile(r"secret", re.I), "column name matches secret"),
    (re.compile(r"token", re.I), "column name matches token"),
    (re.compile(r"api[-_]?key|apikey", re.I), "column name matches api key"),
    (re.compile(r"credential", re.I), "column name matches credential"),
    (re.compile(r"auth[-_]?code|otp|pin[-_]?code", re.I), "column name matches auth code"),
    (re.compile(r"e[-_]?mail", re.I), "column name matches email"),
    (re.compile(r"phone|mobile|tel(ephone)?", re.I), "column name matches phone"),
    (re.compile(r"ssn|social[-_]?security", re.I), "column name matches ssn"),
    (re.compile(r"card", re.I), "column name matches card"),
    (re.compile(r"credit", re.I), "column name matches credit"),
    (re.compile(r"cvv|cvc", re.I), "column name matches cvv"),
    (re.compile(r"iban|bank[-_]?account", re.I), "column name matches bank account"),
    (re.compile(r"private[-_]?key", re.I), "column name matches private key"),
]

# Name matching works on whole words, not raw substrings. The patterns
# above applied with re.search matched the sensitive fragment inside
# unrelated words: "hotel" and "satellite" matched phone (tel),
# "passenger_count" and "compass" matched password (pass), "footprint"
# matched auth code (otp), "discard" and "cardinality" matched card.
# Those columns lost their whole sample to a substring accident.
# name_reason() below tokenises the column name (splitting on
# separators and on camelCase boundaries, so password_hash,
# passwordHash, and PASSWORD_HASH all tokenise alike) and matches
# whole tokens or adjacent token pairs. The reason strings are the
# ones NAME_PATTERNS has always produced, in the same order.

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
_SSN = re.compile(r"^\d{3}-\d{2}-\d{4}$")
_PHONE_CHARS = re.compile(r"^\+?[\d\s().-]+$")
_CARD_CHARS = re.compile(r"^[\d\s-]+$")


def _luhn_ok(digits: str) -> bool:
    """True when a string of decimal digits passes the Luhn checksum
    used by payment card numbers."""
    total = 0
    alt = False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def shape_of(value: str):
    """Return the sensitive shape a string value matches, or None."""
    v = value.strip()
    if not v or len(v) > 254:
        return None
    if _EMAIL.match(v):
        return "email"
    if _SSN.match(v):
        return "ssn"
    digits = re.sub(r"\D", "", v)
    if _CARD_CHARS.match(v) and 13 <= len(digits) <= 19 and _luhn_ok(digits):
        return "card"
    # Phone requires at least one separator or a leading +: bare digit
    # strings are numeric data (ids, squares, counters) far more often
    # than they are phone numbers, and redacting numeric columns on a
    # digit count alone was a measured false positive. Name-based
    # detection still covers columns named phone/mobile/tel.
    if not v.isdigit() and _PHONE_CHARS.match(v) and 10 <= len(digits) <= 15:
        letters = re.sub(r"[\d\s().+-]", "", v)
        if not letters:
            return "phone"
    return None


def shape_of_int(value: int):
    """Return the sensitive shape a native JSON integer matches, or None.

    Only the card shape can apply. A bare integer carries no
    separators, so the email and SSN shapes cannot match, and phone
    detection deliberately requires separators (see shape_of). Card
    numbers stored as JSON numbers do occur, and the Luhn check keeps
    the false-positive rate at the same level as the string path.
    Negative values are never card numbers.
    """
    if value < 0:
        return None
    digits = str(value)
    if 13 <= len(digits) <= 19 and _luhn_ok(digits):
        return "card"
    return None


def _name_tokens(column_name: str):
    """Split a column name into lowercase word tokens.

    Separators (underscore, hyphen, spaces, dots) split, camelCase
    boundaries split (including acronym boundaries: APIKey becomes
    api + key), and trailing digits are dropped (password1 is the
    password word). A glued compound such as "mysecretkey" stays one
    token and no longer matches: that is the accepted price of not
    redacting "hotel" for containing "tel".
    """
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", column_name or "")
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    tokens = []
    for part in re.split(r"[^A-Za-z0-9]+", s):
        token = part.lower().rstrip("0123456789")
        if token:
            tokens.append(token)
    return tokens


def name_reason(column_name: str):
    """Return the redaction reason when a column or key name matches
    a sensitive name pattern (password, token, email, card, and kin),
    or None when no pattern matches."""
    tokens = _name_tokens(column_name)
    if not tokens:
        return None
    have = set(tokens)
    pairs = set(zip(tokens, tokens[1:]))

    def tok(*words):
        return any(w in have for w in words)

    def phrase(a, b):
        # The second word may be pluralised (api_keys, pin_codes).
        return (a, b) in pairs or (a, b + "s") in pairs

    # Rule order mirrors NAME_PATTERNS: the first matching rule wins,
    # so e.g. "credit_card" still reports the card reason.
    if (tok("pass", "password", "passwd", "passphrase")
            or phrase("pass", "word") or phrase("pass", "wd")
            or phrase("pass", "phrase")):
        return "column name matches password"
    if tok("secret", "secrets"):
        return "column name matches secret"
    if tok("token", "tokens"):
        return "column name matches token"
    if tok("apikey", "apikeys") or phrase("api", "key"):
        return "column name matches api key"
    if tok("credential", "credentials"):
        return "column name matches credential"
    if (tok("otp", "authcode", "pincode")
            or phrase("auth", "code") or phrase("pin", "code")):
        return "column name matches auth code"
    if tok("email") or phrase("e", "mail"):
        return "column name matches email"
    if tok("phone", "phones", "mobile", "tel", "telephone",
           "cellphone", "smartphone"):
        return "column name matches phone"
    if tok("ssn") or phrase("social", "security"):
        return "column name matches ssn"
    if tok("card", "cards", "creditcard"):
        return "column name matches card"
    if tok("credit"):
        return "column name matches credit"
    if tok("cvv", "cvc"):
        return "column name matches cvv"
    if tok("iban") or phrase("bank", "account"):
        return "column name matches bank account"
    if phrase("private", "key"):
        return "column name matches private key"
    return None


REDACTED = "[REDACTED]"


def redact_nested(value, path=""):
    """Redact sensitive values inside a nested object or array value.

    Returns (new_value, hits), where hits is a list of (path, reason)
    for every replacement, with paths rooted at ``path`` (a key name
    extends the path with ".key", a list index with "[i]"). The rules
    are the column rules applied at any depth: a key whose name matches
    a sensitive name pattern has its whole value replaced; a string
    matching a sensitive shape is replaced; a native integer matching
    the card shape (via shape_of_int) is replaced. Anything else is
    returned structurally identical, so a value with no sensitive
    content round-trips unchanged.
    """
    # Iterative post-order rebuild with an explicit stack: the
    # recursive version died with RecursionError on deeply nested
    # values that the JSON parser itself accepts (a few hundred
    # levels is enough once the caller's own frames are counted),
    # crashing the whole analysis instead of redacting the sample.
    # Op kinds: "visit" transforms a value; "named" records a
    # name-redacted dict entry; "dict"/"list" assemble a container
    # from the most recent child results. Children are pushed in
    # reverse so they are processed (and hits recorded) in document
    # order, exactly as the recursive version did.
    hits = []
    results = []
    stack = [("visit", value, path)]
    while stack:
        op = stack.pop()
        kind = op[0]
        if kind == "visit":
            _, node, node_path = op
            if isinstance(node, dict):
                keys = list(node.keys())
                stack.append(("dict", keys))
                for key in reversed(keys):
                    sub_path = ("%s.%s" % (node_path, key)
                                if node_path else str(key))
                    reason = name_reason(str(key))
                    if reason:
                        stack.append(("named", sub_path, reason))
                    else:
                        stack.append(("visit", node[key], sub_path))
            elif isinstance(node, (list, tuple)):
                stack.append(("list", len(node)))
                for i in range(len(node) - 1, -1, -1):
                    stack.append(
                        ("visit", node[i], "%s[%d]" % (node_path, i)))
            elif isinstance(node, str):
                shape = shape_of(node)
                if shape:
                    hits.append(
                        (node_path, "value matches %s shape" % shape))
                    results.append(REDACTED)
                else:
                    results.append(node)
            elif isinstance(node, int) and not isinstance(node, bool):
                shape = shape_of_int(node)
                if shape:
                    hits.append(
                        (node_path, "value matches %s shape" % shape))
                    results.append(REDACTED)
                else:
                    results.append(node)
            else:
                results.append(node)
        elif kind == "named":
            _, sub_path, reason = op
            hits.append((sub_path, reason))
            results.append(REDACTED)
        elif kind == "dict":
            _, keys = op
            if keys:
                children = results[-len(keys):]
                del results[-len(keys):]
            else:
                children = []
            results.append(dict(zip(keys, children)))
        else:  # "list"
            _, count = op
            if count:
                children = results[-count:]
                del results[-count:]
            else:
                children = []
            results.append(list(children))
    return results[0], hits


# A column is shape-redacted when at least this share of its checked
# string values match one shape, with a small absolute floor so one
# stray look-alike in a huge column does not trigger it alone.
SHAPE_MIN_HITS = 2
def display_name(name):
    """The name a column is shown under in schema / pack
    output. A header that is really a KEY=VALUE line (an
    .env or .ini read as CSV) carries the secret in the
    name itself: name-based redaction cannot see it (the
    KEY is innocuous) and value redaction never scans
    names. Mask everything after the first '=' so the
    shape of the file stays visible and the value does
    not. (GhostIDE audit A7 observation, Cycle 2 I4.)"""
    if isinstance(name, str) and "=" in name:
        head, _, tail = name.partition("=")
        if tail.strip():
            return head + "=<redacted>"
    return name


SHAPE_MIN_RATIO = 0.2


def shape_reason(shape_hits: dict, strings_checked: int):
    """Decide shape-based redaction from a column's hit counters.

    A shape triggers redaction when it has at least SHAPE_MIN_HITS
    hits covering at least SHAPE_MIN_RATIO of the checked values, or
    when every checked value matches it. The returned reason names
    the shape and the hit count, for example "values match card
    shape (3 of 3 checked)", and never includes a value itself.
    """
    if strings_checked <= 0:
        return None
    for shape, hits in sorted(shape_hits.items()):
        if hits >= SHAPE_MIN_HITS and hits / strings_checked >= SHAPE_MIN_RATIO:
            return "values match %s shape (%d of %d checked)" % (
                shape, hits, strings_checked)
        if hits == strings_checked and hits >= 1:
            return "values match %s shape (%d of %d checked)" % (
                shape, hits, strings_checked)
    return None
