"""Config / data-file slicing (v0.9): the `structure` mode.

Non-code files (YAML, TOML, JSON, SQL, shell, PowerShell) get a real
slicing story. `structure` keeps the shape of a file — key paths,
table/DDL surface, function definitions — and replaces values under
a documented rule. `signatures` on these languages means the same
surface as `structure` (SQL and shell have their own signatures
rendering, below); `interfaces` is the values-free variant (SQL:
CREATE statements only); `strip-tests` leaves these files unchanged.

THE VALUE RULE (security is senior to convenience):
  1. A value under a key whose name looks sensitive is ALWAYS
     replaced by a placeholder, whatever its type or length.
     Sensitive = any name segment (split on non-alphanumerics and
     camelCase boundaries) in {password, passwd, pass, pwd, secret,
     token, key, auth, credential(s), private, session, cookie,
     bearer, jwt}, or the name containing "secret", "password",
     "passwd" or "credential" anywhere. So `db_pass`, `apiToken`,
     `client-secret`, `aws_secret_access_key` are all sensitive,
     while `monkey`, `keyboard`, `tokenizer` are not (segments,
     not substrings, for token/key).
  2. Numbers, booleans and nulls under non-sensitive keys are kept.
     (Under a sensitive key they are placeholdered too: a PIN is
     a number.)
  3. A string under a non-sensitive key is kept only when it is
     clearly an enum-like token: at most 24 characters, matching
     [A-Za-z0-9][A-Za-z0-9._/+:-]* (no spaces, no quotes, no @),
     or an env/placeholder reference (${...}, $VAR, <...>), and not
     random-looking (12+ chars mixing upper, lower and digits with
     per-character entropy >= 3.4 are placeholdered anyway).
     Everything else — long strings, free text, prose, URLs with
     userinfo — becomes a placeholder.
  4. Block scalars (YAML |/>), heredoc bodies used as values, and
     multi-line strings are placeholdered wholesale: their content
     is free text by definition.
Placeholders: `"…"` for YAML/TOML/shell strings, `"…(len N)"` for
non-sensitive JSON strings (JSON shows the length because JSON keys
alone say little), `"…"` for sensitive JSON values.

DEFENCE IN DEPTH: every structure/signatures rendering passes
through `_leak_backstop`, which runs the v0.4 secret scanner over
the OUTPUT and replaces any line it still flags (value portion
only, key prefix preserved). Structure mode must never leak more
than full mode; the tests plant realistic secrets (assembled from
fragments) in every format and assert they never reach the output.

Format notes (parser-lite honesty applies, as everywhere):
  YAML: line-based block rendering. Mapping keys, nested blocks
    and sequences (collapsed to one exemplar + "+N more") are
    understood; flow collections ({...} / [...]) are rendered by a
    small recursive renderer and degrade to a type placeholder
    when they do not parse. Anchors (&a) are kept, aliases (*a)
    pass through (they carry no value). Comments are kept only
    when they are in the leading header block or immediately
    precede a mapping key at the same indent (section headers);
    trailing comments are dropped. Tab-indented files and lines
    that match no known shape degrade to keeping the line (the
    backstop still applies).
  TOML: line-based; table headers kept, dotted keys understood,
    order and layout preserved. Multi-line strings and multi-line
    arrays collapse to a one-line placeholder. Inline tables
    collapse to {…} (their inner values are not rendered). Full-line
    comments follow the YAML rule with "table header" in place of
    "mapping key".
  JSON: real parse (stdlib json); invalid JSON returns the source
    unchanged (same degrade rule as the notebook slicer). Object
    key order is preserved. Arrays render one transformed exemplar
    element plus a "… (N more items)" string element when N > 1.
    A sensitive key's value is replaced wholesale, containers
    included.
  SQL: statement splitter that respects '...' strings ('' escape),
    "..." and `...` quoting, -- and /* */ comments, and Postgres
    dollar-quoting ($$...$$, $tag$...$tag$). CREATE statements are
    the schema surface and are kept in full (both reducing modes);
    `interfaces` drops everything else. Other statements collapse
    to one summary comment: INSERT gets kind + target + a counted
    row total when it has a VALUES list (INSERT ... SELECT is
    labelled not countable); other kinds get kind + target (from
    FROM/INTO/UPDATE/TABLE) + line count. Comments standing alone
    between statements are preserved; comments inside a collapsed
    statement are dropped with it.
  Shell / PowerShell (signatures): function definitions collapse
    to their header line (body = lines up to a closing-brace-only
    line at the definition's indent or shallower), top-level
    variable assignments are kept with values under the value
    rule, and the leading comment block is kept. Shell heredoc
    bodies are never parsed as code (tracked in a pre-pass);
    PowerShell here-strings assigned to a variable are
    placeholdered and their bodies skipped.
"""
from __future__ import annotations

import json
import re

from .secrets_scan import _entropy, scan_text

CONFIG_LANGUAGES = ("yaml", "toml", "json", "sql", "shell", "powershell")

_SENSITIVE_SEGMENTS = {
    "password", "passwd", "pass", "pwd", "secret", "token", "key",
    "auth", "credential", "credentials", "private", "session",
    "cookie", "bearer", "jwt", "apikey",
}
_SENSITIVE_SUBSTRINGS = ("secret", "password", "passwd", "credential")
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")
_WORD_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:\-]*$")
_NUMBER_RE = re.compile(
    r"^-?(0x[0-9a-fA-F_]+|0o[0-7_]+|0b[01_]+|\d[\d_]*(\.\d[\d_]*)?([eE][+-]?\d+)?)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$")
_STRING_PLACEHOLDER = '"…"'


def is_sensitive_key(name: str) -> bool:
    """True when a key/variable name looks sensitive (module rule 1)."""
    if not name:
        return False
    cleaned = name.strip().strip("\"'").strip("$")
    low = cleaned.lower()
    if any(s in low for s in _SENSITIVE_SUBSTRINGS):
        return True
    segments: set[str] = set()
    for chunk in re.split(r"[^A-Za-z0-9]+", cleaned):
        if not chunk:
            continue
        for piece in _CAMEL_RE.findall(chunk):
            segments.add(piece.lower())
        segments.add(chunk.lower())
    return bool(segments & _SENSITIVE_SEGMENTS)


def _random_looking(s: str) -> bool:
    if len(s) < 12:
        return False
    if not (any(c.isupper() for c in s) and any(c.islower() for c in s)
            and any(c.isdigit() for c in s)):
        return False
    return _entropy(s) >= 3.4


def _keep_string(s: str) -> bool:
    """Rule 3: is this string clearly an enum-like, non-sensitive token?"""
    if not s or len(s) > 24:
        return False
    if s.startswith(("${", "$", "<")):
        return True  # env / placeholder reference, not a literal
    if not _WORD_VALUE_RE.match(s):
        return False
    return not _random_looking(s)


def render_scalar(raw: str, key_name: str, *, values: bool = True) -> str:
    """Render one scalar (config text formats) under the value rule.

    `raw` is the value text as written (quotes included if present).
    `values=False` is interfaces mode: every string is placeholdered
    and the placeholder names the type instead.
    """
    text = raw.strip()
    if is_sensitive_key(key_name):
        return _STRING_PLACEHOLDER
    if not values:
        if _is_number(text):
            return text
        if text.lower() in ("true", "false", "null", "~"):
            return text
        return _STRING_PLACEHOLDER
    low = text.lower()
    if low in ("true", "false", "null", "~", "yes", "no", "on", "off") and not text[:1] in "\"'":
        return text
    if _is_number(text) or _DATE_RE.match(text):
        return text
    inner = _unquote(text)
    if inner is None:
        inner = text
    if _keep_string(inner):
        return text
    return _STRING_PLACEHOLDER


def _is_number(text: str) -> bool:
    return bool(_NUMBER_RE.match(text)) or text in ("inf", "-inf", "+inf", "nan", ".inf", "-.inf", ".nan")


def _unquote(text: str) -> str | None:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return None


# ---------------------------------------------------------------------------
# Leak backstop (defence in depth)
# ---------------------------------------------------------------------------

_VALUE_LINE_RE = re.compile(
    r"^(\s*(?:\"[^\"]+\"|'[^']+'|[A-Za-z_$][\w.\-]*)\s*[:=]\s*)(.*)$")


def _leak_backstop(text: str, path: str) -> str:
    """Replace the value portion of any output line the secret
    scanner still flags. The scanner is run as if on a config file
    (path suffix swapped) so bare values are checked too.

    A rewritten line ALWAYS keeps the original line's leading
    indentation (and a leading `- ` sequence marker): in YAML the
    indent IS the structure, so a rewrite that dropped it would
    silently promote a nested key to the top level. The replacement
    is built as indent + body, never trusted to the regex prefix
    (parent finding P0, G5)."""
    if not text.strip():
        return text
    fake = re.sub(r"\.[A-Za-z0-9]+$", ".env", path) if "." in path.rsplit("/", 1)[-1] else path + ".env"
    try:
        findings = scan_text(fake, text)
    except Exception:
        return text
    if not findings:
        return text
    bad = {f["line"] for f in findings}
    lines = text.splitlines()
    for ln in bad:
        if 1 <= ln <= len(lines):
            line = lines[ln - 1]
            indent = line[:len(line) - len(line.lstrip())]
            body = line[len(indent):]
            m = _VALUE_LINE_RE.match(body)
            if m:
                tail = "," if m.group(2).rstrip().endswith(",") else ""
                lines[ln - 1] = indent + m.group(1) + _STRING_PLACEHOLDER + tail
            else:
                marker = "- " if body.startswith("- ") else ""
                lines[ln - 1] = indent + marker + _STRING_PLACEHOLDER
    out = "\n".join(lines)
    return out + ("\n" if text.endswith("\n") else "")


# ---------------------------------------------------------------------------
# Flow collections (YAML {..} / [..], shared by YAML and TOML scalars)
# ---------------------------------------------------------------------------

def _flow_render(text: str, key_name: str, values: bool = True) -> str | None:
    """Render a flow collection; None when it does not parse."""
    parser = _FlowParser(text)
    try:
        rendered, pos = parser.value(0, key_name, values)
    except _FlowError:
        return None
    if text[pos:].strip().strip(","):
        return None
    return rendered


class _FlowError(Exception):
    pass


class _FlowParser:
    def __init__(self, text: str):
        self.s = text
        self.n = len(text)

    def _ws(self, i: int) -> int:
        while i < self.n and self.s[i] in " \t":
            i += 1
        return i

    def value(self, i: int, key_name: str, values: bool, depth: int = 0):
        if depth > 4:
            raise _FlowError("deep")
        i = self._ws(i)
        if i >= self.n:
            raise _FlowError("eof")
        ch = self.s[i]
        if ch == "{":
            return self._map(i, key_name, values, depth)
        if ch == "[":
            return self._seq(i, key_name, values, depth)
        if ch in "\"'":
            j = i + 1
            while j < self.n:
                if self.s[j] == "\\" and ch == '"':
                    j += 2
                    continue
                if self.s[j] == ch:
                    break
                j += 1
            if j >= self.n:
                raise _FlowError("unterminated string")
            raw = self.s[i:j + 1]
            return render_scalar(raw, key_name, values=values), j + 1
        # bare token up to a flow delimiter
        j = i
        while j < self.n and self.s[j] not in ",}]":
            j += 1
        raw = self.s[i:j].strip()
        if not raw:
            raise _FlowError("empty token")
        return render_scalar(raw, key_name, values=values), j

    def _map(self, i: int, key_name: str, values: bool, depth: int):
        parts: list[str] = []
        i = self._ws(i + 1)
        if i < self.n and self.s[i] == "}":
            return "{}", i + 1
        while True:
            i = self._ws(i)
            # key: bare or quoted, up to ':'
            if i < self.n and self.s[i] in "\"'":
                q = self.s[i]
                j = self.s.find(q, i + 1)
                if j < 0:
                    raise _FlowError("bad key")
                key = self.s[i + 1:j]
                i = j + 1
            else:
                m = re.match(r"[^:,\{\}]+", self.s[i:])
                if not m:
                    raise _FlowError("bad key")
                key = m.group(0).strip()
                i += len(m.group(0))
            i = self._ws(i)
            if i >= self.n or self.s[i] != ":":
                raise _FlowError("no colon")
            rendered, i = self.value(i + 1, key, values, depth + 1)
            parts.append(f"{key}: {rendered}")
            i = self._ws(i)
            if i < self.n and self.s[i] == ",":
                i += 1
                continue
            if i < self.n and self.s[i] == "}":
                return "{ " + ", ".join(parts) + " }", i + 1
            raise _FlowError("map tail")

    def _seq(self, i: int, key_name: str, values: bool, depth: int):
        parts: list[str] = []
        i = self._ws(i + 1)
        if i < self.n and self.s[i] == "]":
            return "[]", i + 1
        while True:
            rendered, i = self.value(i, key_name, values, depth + 1)
            parts.append(rendered)
            i = self._ws(i)
            if i < self.n and self.s[i] == ",":
                i += 1
                continue
            if i < self.n and self.s[i] == "]":
                if len(parts) > 8:
                    shown = ", ".join(parts[:3])
                    return f"[{shown}, … (+{len(parts) - 3})]", i + 1
                return "[" + ", ".join(parts) + "]", i + 1
            raise _FlowError("seq tail")


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------

_YAML_KEY_RE = re.compile(
    r"^(?P<key>\"[^\"]*\"|'[^']*'|[^:\s#][^:]*?)\s*:\s*(?P<rest>.*)$")
_YAML_ITEM_RE = re.compile(r"^-(?:\s+(?P<rest>.*))?$")


def _yaml_entries(source: str):
    entries = []
    for raw in source.splitlines():
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if not stripped:
            kind = "blank"
        elif stripped.startswith("#"):
            kind = "comment"
        elif stripped in ("---", "...") or stripped.startswith("--- "):
            kind = "doc"
        elif _YAML_ITEM_RE.match(stripped):
            kind = "item"
        elif _YAML_KEY_RE.match(stripped):
            kind = "key"
        else:
            kind = "other"
        entries.append({"indent": indent, "text": stripped, "raw": raw.rstrip(), "kind": kind})
    return entries


def _yaml_key_parts(entry) -> tuple[str, str]:
    m = _YAML_KEY_RE.match(entry["text"])
    if not m:
        return entry["text"], ""
    key = m.group("key").strip().strip("\"'")
    return key, m.group("rest").strip()


def slice_yaml(source: str, mode: str, path: str = "") -> str:
    values = mode != "interfaces"
    if any(re.match(r"^[ \t]*\t", ln) for ln in source.splitlines() if ln.strip()):
        return source  # tab indentation is invalid YAML; keep more
    entries = _yaml_entries(source)
    keep_comment = _yaml_comment_policy(entries)
    out, _ = _yaml_block(entries, 0, len(entries), -1, [], values, keep_comment)
    text = "\n".join(out).strip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _leak_backstop(text + ("\n" if text else ""), path or "file.yaml")
    return text


def _yaml_comment_policy(entries) -> set[int]:
    """Indices of comment entries to keep: leading header block, or a
    comment whose next content line is a mapping key at the same
    indent (a section header)."""
    keep: set[int] = set()
    n = len(entries)
    i = 0
    while i < n and entries[i]["kind"] in ("comment", "blank"):
        if entries[i]["kind"] == "comment":
            keep.add(i)
        i += 1
    for idx, e in enumerate(entries):
        if e["kind"] != "comment" or idx in keep:
            continue
        j = idx + 1
        while j < n and entries[j]["kind"] in ("blank", "comment"):
            j += 1
        if j < n and entries[j]["kind"] == "key" and entries[j]["indent"] == e["indent"]:
            keep.add(idx)
    return keep


def _yaml_block(entries, lo, hi, parent_indent, stack, values, keep_comment):
    """Render entries[lo:hi] whose indent is > parent_indent.

    `stack` holds (indent, key) of enclosing mapping keys, for
    sensitive-key inheritance into sequence items.
    Returns (lines, next_index)."""
    out: list[str] = []
    local = list(stack)
    i = lo
    while i < hi:
        e = entries[i]
        if e["indent"] <= parent_indent:
            break
        if e["kind"] == "blank":
            i += 1
            continue
        if e["kind"] == "comment":
            if i in keep_comment:
                out.append(e["raw"])
            i += 1
            continue
        if e["kind"] in ("key", "item", "other"):
            # An item at a key's own indent may belong to that key
            # (indentless sequences), so items only pop strictly
            # deeper keys; keys/other lines pop same-indent keys.
            limit = e["indent"] + 1 if e["kind"] == "item" else e["indent"]
            while local and local[-1][0] >= limit:
                local.pop()
        if e["kind"] == "doc":
            out.append(e["raw"])
            local = []
            i += 1
            continue
        if e["kind"] == "item":
            lines, i = _yaml_sequence(entries, i, hi, local, values, keep_comment)
            out.extend(lines)
            continue
        if e["kind"] == "key":
            key, rest = _yaml_key_parts(e)
            ind = e["indent"]
            pad = " " * ind
            if rest == "":
                out.append(f"{pad}{e['text']}")
                # The key owns whatever follows at a deeper indent
                # AND any indentless sequence at its own indent, so
                # it goes on the block stack either way (audit F1);
                # recursion consumes the deeper children when present.
                local.append((ind, key))
                i += 1
                sub, i = _yaml_block(entries, i, hi, ind, local, values, keep_comment) \
                    if i < hi and entries[i]["indent"] > ind else ([], i)
                out.extend(sub)
                continue
            rendered, consumed = _yaml_value(entries, i, key, rest, values)
            out.append(f"{pad}{_yaml_key_text(e)}: {rendered}")
            i += consumed
            continue
        # 'other' lines: keep more (backstop still applies)
        out.append(e["raw"])
        i += 1
    return out, i


def _yaml_key_text(entry) -> str:
    m = _YAML_KEY_RE.match(entry["text"])
    return m.group("key").strip() if m else entry["text"]


def _yaml_value(entries, i, key, rest, values):
    """Render the inline value of a key line; returns (text, lines consumed)."""
    e = entries[i]
    # anchors: &name <value> keeps the anchor; *alias carries no value
    anchor = ""
    m = re.match(r"^(&[\w.\-]+)\s+(.*)$", rest)
    if m:
        anchor, rest = m.group(1) + " ", m.group(2).strip()
    if re.match(r"^\*[\w.\-]+$", rest):
        return anchor + rest, 1
    if rest[:1] in "|>" and re.match(r"^[|>][+-]?\d*\s*(#.*)?$", rest):
        # block scalar: placeholder; consume its indented body
        j = i + 1
        while j < len(entries):
            nxt = entries[j]
            if nxt["kind"] == "blank":
                j += 1
                continue
            if nxt["indent"] > e["indent"]:
                j += 1
                continue
            break
        return _STRING_PLACEHOLDER, j - i
    if rest[:1] in "{[":
        # flow collection, possibly spanning following deeper lines
        joined = rest
        j = i
        while not _flow_balanced(joined) and j + 1 < len(entries) \
                and entries[j + 1]["indent"] > e["indent"]:
            j += 1
            joined += " " + entries[j]["text"]
        rendered = _flow_render(joined, key, values)
        if rendered is None:
            rendered = "{…}" if rest.startswith("{") else "[…]"
        return anchor + rendered, j - i + 1
    # plain / quoted scalar (a trailing comment is dropped)
    scalar = re.sub(r"\s+#.*$", "", rest).strip()
    return anchor + render_scalar(scalar, key, values=values), 1


def _flow_balanced(text: str) -> bool:
    depth = 0
    quote = None
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
    return depth <= 0


def _yaml_sequence(entries, lo, hi, stack, values, keep_comment):
    """Collapse a sequence: first item rendered, the rest counted."""
    first_indent = entries[lo]["indent"]
    parent_key = ""
    for ind, key in reversed(stack):
        if ind <= first_indent:
            parent_key = key
            break
    items: list[tuple[int, int]] = []  # (start, end) entry spans
    i = lo
    while i < hi:
        e = entries[i]
        if e["kind"] in ("blank", "comment"):
            i += 1  # separators between items do not end the sequence
            continue
        if e["kind"] != "item" or e["indent"] != first_indent:
            break
        start = i
        i += 1
        last_content = i
        while i < hi:
            nxt = entries[i]
            if nxt["kind"] in ("blank", "comment"):
                i += 1  # tentative: belongs to the span if content follows
                continue
            if nxt["indent"] > first_indent:
                i += 1
                last_content = i
                continue
            break
        items.append((start, last_content))
    if not items:
        return [], lo + 1
    if parent_key and is_sensitive_key(parent_key):
        # A sensitive key's sequence collapses wholesale (audit F3),
        # matching the JSON rule for containers under sensitive keys.
        out = [f"{' ' * first_indent}- {_STRING_PLACEHOLDER}"]
        if len(items) > 1:
            out.append(f"{' ' * first_indent}- … (+{len(items) - 1} more)")
        return out, items[-1][1]
    # render the first item: dash line becomes a synthetic entry at
    # indent+2 whose text is the item's inline content.
    start, end = items[0]
    first = entries[start]
    m = _YAML_ITEM_RE.match(first["text"])
    rest = (m.group("rest") or "").strip() if m else ""
    pad0 = " " * first_indent
    if rest[:1] in "{[":
        # flow-style item (audit G2): render through the flow
        # renderer, joining span lines when it spans several.
        joined = rest
        k = start + 1
        while not _flow_balanced(joined) and k < end:
            joined += " " + entries[k]["text"]
            k += 1
        rendered = _flow_render(joined, parent_key, values)
        if rendered is None:
            rendered = "{…}" if rest.startswith("{") else "[…]"
        out = [f"{pad0}- {rendered}"]
        if len(items) > 1:
            out.append(f"{pad0}- … (+{len(items) - 1} more)")
        return out, items[-1][1]
    sub = []
    if rest:
        sub.append({"indent": first_indent + 2, "text": rest, "raw": " " * (first_indent + 2) + rest,
                    "kind": "key" if _YAML_KEY_RE.match(rest) else
                            ("item" if _YAML_ITEM_RE.match(rest) else "scalar")})
    for k in range(start + 1, end):
        sub.append(entries[k])
    pad = " " * first_indent
    if sub and sub[0]["kind"] == "scalar":
        rendered = render_scalar(rest, parent_key, values=values)
        out = [f"{pad}- {rendered}"]
    else:
        rendered_lines, _ = _yaml_block(sub, 0, len(sub), first_indent, stack, values, keep_comment)
        out = []
        for n, line in enumerate(rendered_lines):
            if n == 0:
                inner = line[first_indent + 2:] if len(line) > first_indent + 2 else line.lstrip()
                out.append(f"{pad}- {inner}")
            else:
                out.append(line)
        if not out:
            out = [f"{pad}- {_STRING_PLACEHOLDER}"]
    if len(items) > 1:
        out.append(f"{pad}- … (+{len(items) - 1} more)")
    return out, items[-1][1]


# ---------------------------------------------------------------------------
# TOML
# ---------------------------------------------------------------------------

_TOML_HEADER_RE = re.compile(r"^\[\[?[^\]]+\]\]?")
_TOML_KEYVAL_RE = re.compile(r"^(?P<key>[^=]+?)\s*=\s*(?P<val>.*)$")


def _toml_comment_policy(lines) -> set[int]:
    keep: set[int] = set()
    n = len(lines)
    i = 0
    while i < n and (not lines[i].strip() or lines[i].strip().startswith("#")):
        if lines[i].strip().startswith("#"):
            keep.add(i)
        i += 1
    for idx, ln in enumerate(lines):
        if not ln.strip().startswith("#") or idx in keep:
            continue
        j = idx + 1
        while j < n and (not lines[j].strip() or lines[j].strip().startswith("#")):
            j += 1
        if j < n and _TOML_HEADER_RE.match(lines[j].strip()):
            keep.add(idx)
    return keep


def slice_toml(source: str, mode: str, path: str = "") -> str:
    values = mode != "interfaces"
    lines = source.splitlines()
    keep_comment = _toml_comment_policy(lines)
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("#"):
            if i in keep_comment:
                out.append(raw.rstrip())
            i += 1
            continue
        if _TOML_HEADER_RE.match(stripped):
            out.append(stripped)
            i += 1
            continue
        m = _TOML_KEYVAL_RE.match(stripped)
        if not m:
            out.append(raw.rstrip())  # unknown shape: keep more
            i += 1
            continue
        key_text = m.group("key").strip()
        key_name = key_text.split(".")[-1].strip().strip("\"'")
        sensitive = any(is_sensitive_key(seg.strip().strip("\"'"))
                        for seg in key_text.split("."))
        val = m.group("val").strip()
        if not val.startswith(('"""', "'''")):
            val = _toml_strip_comment(val)
        # multi-line basic/literal string
        if val.startswith(('"""', "'''")):
            delim = val[:3]
            out.append(f"{key_text} = {_STRING_PLACEHOLDER}")
            if val.count(delim) < 2 or (len(val) >= 6 and val[3:].find(delim) < 0):
                i += 1
                while i < n and delim not in lines[i]:
                    i += 1
                i += 1  # consume closing line
            else:
                i += 1
            continue
        # array: possibly multi-line
        if val.startswith("["):
            if not _flow_balanced(val):
                out.append(f"{key_text} = […]")
                depth = val.count("[") - val.count("]")
                i += 1
                while i < n and depth > 0:
                    depth += lines[i].count("[") - lines[i].count("]")
                    i += 1
                continue
            if sensitive:
                out.append(f"{key_text} = {_STRING_PLACEHOLDER}")
            else:
                rendered = _toml_array(val, key_name, values)
                out.append(f"{key_text} = {rendered}")
            i += 1
            continue
        if val.startswith("{"):
            out.append(f"{key_text} = " + ("{…}" if not sensitive else _STRING_PLACEHOLDER))
            i += 1
            continue
        if sensitive:
            out.append(f"{key_text} = {_STRING_PLACEHOLDER}")
            i += 1
            continue
        out.append(f"{key_text} = {render_scalar(val, key_name, values=values)}")
        i += 1
    text = "\n".join(out).strip("\n")
    text = _leak_backstop(text + ("\n" if text else ""), path or "file.toml")
    return text


def _toml_strip_comment(val: str) -> str:
    """Drop a trailing ` # comment` that sits outside any string."""
    quote = None
    i = 0
    while i < len(val):
        ch = val[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or val[i - 1] in " \t"):
            return val[:i].rstrip()
        i += 1
    return val


def _toml_array(val: str, key_name: str, values: bool) -> str:
    inner = val.strip()[1:-1].strip() if val.strip().endswith("]") else ""
    if not inner:
        return "[]"
    parts = _split_flow_items(inner)
    if parts is None:
        return "[…]"
    rendered = [render_scalar(p.strip(), key_name, values=values) for p in parts]
    if len(rendered) > 8:
        rendered = rendered[:3] + [f"… (+{len(rendered) - 3})"]
    return "[" + ", ".join(rendered) + "]"


def _split_flow_items(inner: str) -> list[str] | None:
    parts, depth, quote, cur = [], 0, None, ""
    for ch in inner:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "[{":
            depth += 1
            cur += ch
        elif ch in "]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if quote or depth != 0:
        return None
    if cur.strip():
        parts.append(cur)
    return parts


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def slice_json(source: str, mode: str, path: str = "") -> str:
    values = mode != "interfaces"
    try:
        data = json.loads(source)
    except Exception:
        return source  # invalid JSON degrades to full, unchanged
    try:
        shaped = _json_shape(data, "", values, 0)
    except RecursionError:
        # v0.21: nesting that parses but is too deep to shape-walk
        # degrades to full, like invalid JSON — never a crash.
        return source
    text = json.dumps(shaped, indent=2, ensure_ascii=False)
    return _leak_backstop(text + "\n", path or "file.json")


def _json_category(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, dict):
        return "dict"
    if isinstance(v, list):
        return "list"
    if isinstance(v, str):
        return "str"
    if v is None:
        return "null"
    return "num"


def _json_homogeneous(values) -> bool:
    cats = {_json_category(v) for v in values}
    return len(cats) == 1


def _json_shape(value, key_name: str, values: bool, depth: int):
    if is_sensitive_key(key_name):
        return "…"
    if depth > 100:
        # v0.21: depth bound — real configs nest a handful of
        # levels; beyond this the shape is a placeholder, which
        # also keeps the walk far from the recursion limit.
        return "…"
    if isinstance(value, dict):
        items = list(value.items())
        if len(items) > 20 and "…" not in value and _json_homogeneous(value.values()):
            k0, v0 = items[0]
            shaped = {k0: _json_shape(v0, k0, values, depth + 1)}
            shaped["…"] = f"(+{len(items) - 1} more entries)"
            return shaped
        return {k: _json_shape(v, k, values, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        exemplar = _json_shape(value[0], key_name, values, depth + 1)
        if len(value) == 1:
            return [exemplar]
        return [exemplar, f"… ({len(value) - 1} more items)"]
    if isinstance(value, str):
        if not values:
            return "…"
        if _keep_string(value):
            return value
        return f"…(len {len(value)})"
    return value  # numbers, booleans, null are kept


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def _sql_segments(source: str) -> list[tuple[str, str]]:
    """Split SQL into ('comment'|'statement', text) segments."""
    segs: list[tuple[str, str]] = []
    buf: list[str] = []
    i, n = 0, len(source)

    def flush_stmt():
        text = "".join(buf).strip()
        if text:
            segs.append(("statement", "".join(buf)))
        buf.clear()

    while i < n:
        ch = source[i]
        two = source[i:i + 2]
        # comments
        if two == "--" and (i + 2 >= n or source[i + 2] in " \t\r\n"):
            j = source.find("\n", i)
            if j < 0:
                j = n
            comment = source[i:j]
            if "".join(buf).strip():
                buf.append(comment)  # mid-statement: part of the statement
            else:
                buf.clear()
                segs.append(("comment", comment))
            i = j
            continue
        if two == "/*":
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            comment = source[i:j]
            if "".join(buf).strip():
                buf.append(comment)
            else:
                buf.clear()
                segs.append(("comment", comment))
            i = j
            continue
        if ch in "'\"`":
            q = ch
            j = i + 1
            while j < n:
                if source[j] == q:
                    if q == "'" and j + 1 < n and source[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            buf.append(source[i:j])
            i = j
            continue
        if ch == "$":
            m = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", source[i:])
            if m:
                tag = m.group(0)
                j = source.find(tag, i + len(tag))
                j = n if j < 0 else j + len(tag)
                buf.append(source[i:j])
                i = j
                continue
        if ch == ";":
            buf.append(ch)
            flush_stmt()
            i += 1
            continue
        buf.append(ch)
        i += 1
    flush_stmt()
    return segs


def _sql_target(stmt: str, kind: str) -> str:
    patterns = {
        "INSERT": r"\bINTO\s+([A-Za-z_][\w.\"$]*)",
        "UPDATE": r"^\s*UPDATE\s+([A-Za-z_][\w.\"$]*)",
        "DELETE": r"\bFROM\s+([A-Za-z_][\w.\"$]*)",
        "SELECT": r"\bFROM\s+([A-Za-z_][\w.\"$]*)",
        "DROP": r"\b(?:TABLE|INDEX|VIEW)\s+(?:IF\s+EXISTS\s+)?([A-Za-z_][\w.\"$]*)",
        "ALTER": r"\bTABLE\s+([A-Za-z_][\w.\"$]*)",
        "GRANT": r"\bON\s+([A-Za-z_][\w.\"$]*)",
        "TRUNCATE": r"\bTABLE\s+([A-Za-z_][\w.\"$]*)",
    }
    pat = patterns.get(kind)
    if pat:
        m = re.search(pat, stmt, re.IGNORECASE)
        if m:
            return m.group(1)
    m = re.search(r"\bFROM\s+([A-Za-z_][\w.\"$]*)", stmt, re.IGNORECASE)
    return m.group(1) if m else ""


def _sql_values_rows(stmt: str) -> int | None:
    """Count top-level (...) groups after VALUES; None if no VALUES list."""
    m = re.search(r"\bVALUES\b", stmt, re.IGNORECASE)
    if not m:
        return None
    rest = stmt[m.end():]
    rows = 0
    depth = 0
    quote = None
    started = False
    i = 0
    while i < len(rest):
        ch = rest[i]
        if quote:
            if ch == quote:
                if quote == "'" and i + 1 < len(rest) and rest[i + 1] == "'":
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
        elif ch == "(":
            if depth == 0:
                rows += 1
                started = True
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth == 0:
            break
        i += 1
    return rows if started else None


def slice_sql(source: str, mode: str, path: str = "") -> str:
    out: list[str] = []
    for kind, text in _sql_segments(source):
        if kind == "comment":
            out.append(text.strip())
            continue
        stmt = text.strip()
        first = re.match(r"^\s*([A-Za-z]+)", stmt)
        kw = first.group(1).upper() if first else ""
        if kw == "CREATE":
            out.append(stmt)
            continue
        if mode == "interfaces":
            continue  # interfaces = CREATE surface only
        target = _sql_target(stmt, kw)
        nlines = stmt.count("\n") + 1
        if kw == "INSERT":
            rows = _sql_values_rows(stmt)
            if rows is None:
                out.append(f"-- INSERT INTO {target} (from SELECT or expression; rows not countable)".rstrip())
            else:
                out.append(f"-- INSERT INTO {target}: {rows} row(s) collapsed")
        else:
            label = kw or "STATEMENT"
            tgt = f" {target}" if target else ""
            out.append(f"-- {label}{tgt}: statement collapsed "
                       f"({nlines} line{'s' if nlines != 1 else ''})")
    text = "\n".join(s for s in out if s).strip("\n")
    return text + ("\n" if text else "")


# ---------------------------------------------------------------------------
# Shell / PowerShell signatures
# ---------------------------------------------------------------------------

_SH_FUNC_RES = [
    re.compile(r"^\s*function\s+([A-Za-z_][\w]*)\s*(?:\(\s*\))?\s*(\{)?"),
    re.compile(r"^\s*([A-Za-z_][\w]*)\s*\(\s*\)\s*(\{)?"),
]
_SH_ASSIGN_RE = re.compile(
    r"^(?P<indent>\s*)(?P<prefix>(?:export|readonly|declare(?:\s+-\w+)?|typeset(?:\s+-\w+)?|local)\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<val>.*)$")
_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


def _heredoc_lines(lines: list[str]) -> set[int]:
    """Indices of lines that are heredoc bodies/terminators."""
    body: set[int] = set()
    pending: list[str] = []
    for idx, line in enumerate(lines):
        if pending:
            body.add(idx)
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        if "((" in line.split("<<")[0] if "<<" in line else False:
            continue
        for m in _HEREDOC_RE.finditer(line):
            pending.append(m.group(1))
    return body


def slice_shell(source: str, mode: str, path: str = "") -> str:
    lines = source.splitlines()
    heredoc = _heredoc_lines(lines)
    out: list[str] = []
    i = 0
    n = len(lines)
    in_header = True
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if i in heredoc:
            i += 1
            continue
        if not stripped:
            if in_header:
                out.append(line)
            i += 1
            continue
        if stripped.startswith("#"):
            if in_header or i == 0:
                out.append(line.rstrip())
            i += 1
            continue
        in_header = False
        fm = None
        for rx in _SH_FUNC_RES:
            fm = rx.match(line)
            if fm:
                break
        if fm:
            indent = line[:len(line) - len(line.lstrip())]
            name = fm.group(1)
            has_brace = "{" in line
            closes_same = has_brace and "}" in line[line.find("{") + 1:]
            if closes_same:
                # One-line bodies collapse too (audit F2): a body on
                # one line can hold an assignment-shaped secret.
                out.append(f"{indent}{name}() {{ # ... }}")
                i += 1
                continue
            if has_brace:
                out.append(f"{indent}{name}() {{ # ... }}")
                i += 1
                # skip body until a }-only line at indent <= def indent
                while i < n:
                    if lines[i].strip() == "}" and \
                            (len(lines[i]) - len(lines[i].lstrip())) <= len(indent):
                        i += 1
                        break
                    i += 1
                continue
            out.append(line.rstrip())
            i += 1
            continue
        am = _SH_ASSIGN_RE.match(line)
        if am:
            prefix = am.group("prefix") or ""
            name = am.group("name")
            val = am.group("val").strip()
            rendered = _shell_value(val, name)
            out.append(f"{am.group('indent')}{prefix}{name}={rendered}")
            i += 1
            continue
        i += 1  # other top-level commands are not signature surface
    text = "\n".join(out).strip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _leak_backstop(text + ("\n" if text else ""), path or "file.sh")


def _shell_value(val: str, name: str) -> str:
    if is_sensitive_key(name):
        return _STRING_PLACEHOLDER
    if val.startswith("$(") or val.startswith("`"):
        return val  # command substitution: code, not a literal
    if val.startswith(('"', "'")):
        q = val[0]
        end = val.find(q, 1)
        inner = val[1:end] if end > 0 else val[1:]
        if _keep_string(inner) and "$" not in inner:
            return val[:end + 1] if end > 0 else val
        return _STRING_PLACEHOLDER
    token = val.split()[0] if val.split() else ""
    rest = val[len(token):]
    if _keep_string(token) or token.startswith("$"):
        return token + rest if not rest.strip().startswith("#") else token
    return _STRING_PLACEHOLDER


_PS_FUNC_RE = re.compile(r"^\s*function\s+([\w\-]+)\s*(\([^)]*\))?\s*(\{)?", re.IGNORECASE)
_PS_ASSIGN_RE = re.compile(
    r"^(?P<indent>\s*)\$(?P<scope>script:|global:|local:|env:)?"
    r"(?P<name>[A-Za-z_][\w]*)\s*=\s*(?P<val>.*)$", re.IGNORECASE)


def slice_powershell(source: str, mode: str, path: str = "") -> str:
    lines = source.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    in_header = True
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            if in_header:
                out.append(line)
            i += 1
            continue
        if stripped.startswith("#") or stripped.startswith("<#"):
            if in_header:
                out.append(line.rstrip())
                if stripped.startswith("<#") and "#>" not in stripped:
                    i += 1
                    while i < n:
                        out.append(lines[i].rstrip())
                        if "#>" in lines[i]:
                            i += 1
                            break
                        i += 1
                    continue
            i += 1
            continue
        in_header = False
        fm = _PS_FUNC_RE.match(line)
        if fm:
            indent = line[:len(line) - len(line.lstrip())]
            if "{" in line and "}" in line[line.find("{") + 1:]:
                # One-line bodies collapse too (audit F2).
                head = line[:line.find("{")].rstrip()
                out.append(f"{head} {{ # ... }}")
                i += 1
                continue
            if "{" in line:
                head = line[:line.find("{")].rstrip()
                out.append(f"{head} {{ # ... }}")
                i += 1
                while i < n:
                    if lines[i].strip() == "}" and \
                            (len(lines[i]) - len(lines[i].lstrip())) <= len(indent):
                        i += 1
                        break
                    i += 1
                continue
            out.append(line.rstrip())
            i += 1
            continue
        am = _PS_ASSIGN_RE.match(line)
        if am:
            scope = am.group("scope") or ""
            name = am.group("name")
            val = am.group("val").strip()
            lhs = f"{am.group('indent')}${scope}{name}"
            if re.match(r"^@[\"']\s*(#.*)?$", val):
                out.append(f"{lhs} = {_STRING_PLACEHOLDER}")
                endmark = '"@' if val.startswith('@"') else "'@"
                i += 1
                while i < n and not lines[i].lstrip().startswith(endmark):
                    i += 1
                i += 1
                continue
            if is_sensitive_key(name) or (scope and scope.lower() == "env:" and is_sensitive_key(name)):
                out.append(f"{lhs} = {_STRING_PLACEHOLDER}")
                i += 1
                continue
            if val.startswith("$(") or val.startswith("("):
                out.append(f"{lhs} = {val}")
                i += 1
                continue
            if val.startswith(('"', "'")):
                q = val[0]
                end = val.find(q, 1)
                inner = val[1:end] if end > 0 else val[1:]
                if _keep_string(inner) and "$" not in inner:
                    out.append(f"{lhs} = {val[:end + 1] if end > 0 else val}")
                else:
                    out.append(f"{lhs} = {_STRING_PLACEHOLDER}")
                i += 1
                continue
            token = val.split()[0] if val.split() else ""
            if _is_number(token) or token.startswith("$"):
                out.append(f"{lhs} = {val}")
            elif _keep_string(token):
                out.append(f"{lhs} = {token}")
            else:
                out.append(f"{lhs} = {_STRING_PLACEHOLDER}")
            i += 1
            continue
        i += 1
    text = "\n".join(out).strip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _leak_backstop(text + ("\n" if text else ""), path or "file.ps1")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def slice_config(source: str, language: str, mode: str, path: str = "") -> str:
    """Slice a config/data file. Caller guarantees mode is a reducing
    mode (signatures / interfaces / structure) and language is in
    CONFIG_LANGUAGES."""
    if language == "yaml":
        return slice_yaml(source, mode, path)
    if language == "toml":
        return slice_toml(source, mode, path)
    if language == "json":
        return slice_json(source, mode, path)
    if language == "sql":
        return slice_sql(source, mode, path)
    if language == "shell":
        return slice_shell(source, mode, path)
    if language == "powershell":
        return slice_powershell(source, mode, path)
    return source
