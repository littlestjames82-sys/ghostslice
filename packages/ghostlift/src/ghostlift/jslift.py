"""Tier 2 structured lift for JavaScript artifacts (core).

This module promotes the tested example lifter (``examples/js_lift_demo.py``)
into the GhostLift core, so ``ghostlift inspect`` / ``ghostlift lift``
handle a ``.js`` artifact directly instead of only reporting it as
not liftable. It does three things, and nothing more:

* beautify: put minified JavaScript back into indented, line-broken
  form without changing the tokens;
* find function boundaries: report named function declarations and
  ``const name = (...) =>`` arrow functions, in source order;
* watermark: stamp the output as a Tier 2 lifted reconstruction.

Robustness over the example scanner, both covered by tests:

* Regular-expression literals are recognised with the standard
  previous-significant-token heuristic, so braces and semicolons
  inside a pattern (``/a{2};b/``) are kept inside the literal chunk
  instead of being mistaken for block structure. Division operators
  are not mistaken for regex starts when the previous token is a
  value (identifier, number, string, ``)``, ``]``).
* Semicolons inside parentheses (``for (let i = 0; i < n; i++)``)
  do not start a new line; only top-level semicolons do.
* Function-boundary search runs on code with strings, comments,
  regex literals and template literals masked out, so a literal
  containing the text ``function fake()`` is not reported as a
  function.

Limits, stated plainly: the regex/division heuristic can still be
fooled by constructs such as a regex immediately after ``}`` (block
end vs object literal is genuinely ambiguous without a full parser),
and template literals are kept as one chunk, so ``${...}``
expressions inside them are not beautified internally. Variable
names that minification destroyed stay destroyed: a one-letter name
in the bundle is a one-letter name in the lift.

Stdlib only. Static text work only: this module never runs the
JavaScript it lifts.
"""

from __future__ import annotations

import re
from pathlib import Path

WATERMARK_JS = "/* ghostlift: lifted tier=2 source=minified-js reconstruction=structured */"

_FUNCTION_DECL = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")
_ARROW_CONST = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)

# Keywords after which a "/" begins a regex literal rather than division.
_REGEX_PREFIX_KEYWORDS = {
    "return", "typeof", "case", "in", "of", "new", "delete",
    "void", "do", "else", "instanceof", "yield", "await",
}
# Punctuation after which a "/" begins a regex literal.
_REGEX_PREFIX_CHARS = set("(,=:[!&|?{};+-*%~^<>/")

__all__ = [
    "WATERMARK_JS",
    "beautify",
    "beautify_js",
    "find_function_boundaries",
    "lift_javascript",
    "lift_minified_js",
]


def _coerce_text(source) -> str:
    """Accept JS text, UTF-8 bytes, or a path to a .js file."""
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    if isinstance(source, (bytes, bytearray)):
        return bytes(source).decode("utf-8")
    if isinstance(source, str):
        # A short string that names an existing file is a path; real
        # source text (full of braces/semicolons/newlines) never is.
        if len(source) < 260 and "\n" not in source and ";" not in source:
            candidate = Path(source)
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
        return source
    raise TypeError(f"expected str, bytes, or Path, got {type(source).__name__}")


def _scan(source: str):
    """Yield ``(kind, text)`` spans.

    ``kind`` is ``code`` (single characters), ``string``, ``template``,
    ``comment``, or ``regex``. Non-code spans are yielded whole so
    their contents can never be mistaken for structure.
    """
    i, n = 0, len(source)
    prev_char: str | None = None  # last significant code character
    last_word = ""                 # last completed identifier/keyword
    pending_word = ""

    def note_code_char(ch: str) -> None:
        nonlocal prev_char, last_word, pending_word
        if ch.isalnum() or ch in "_$":
            pending_word += ch
            prev_char = ch
            return
        if pending_word:
            last_word = pending_word
            pending_word = ""
        if ch not in " \t\r\n":
            prev_char = ch

    while i < n:
        ch = source[i]
        if ch in ("'", '"', "`"):
            kind = "template" if ch == "`" else "string"
            j = i + 1
            while j < n:
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == ch:
                    j += 1
                    break
                j += 1
            yield kind, source[i:j]
            prev_char, last_word, pending_word = ch, "", ""
            i = j
        elif source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j == -1 else j
            yield "comment", source[i:j]
            i = j
        elif source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j == -1 else j + 2
            yield "comment", source[i:j]
            i = j
        elif ch == "/" and (
            prev_char is None
            or prev_char in _REGEX_PREFIX_CHARS
            # The previous token is the word still being built if one
            # is, otherwise the last completed word: in "return a / b"
            # the token before "/" is "a" (division), not "return".
            or (pending_word or last_word) in _REGEX_PREFIX_KEYWORDS
        ):
            # Regex literal: scan to the closing "/" outside any
            # character class, then consume trailing flags.
            j = i + 1
            in_class = False
            while j < n:
                c = source[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    j += 1
                    break
                elif c == "\n":
                    break  # unterminated regex: stop at the line end
                j += 1
            while j < n and (source[j].isalpha()):
                j += 1
            yield "regex", source[i:j]
            prev_char, last_word, pending_word = "/", "", ""
            i = j
        else:
            note_code_char(ch)
            yield "code", ch
            i += 1


def _masked_code(source: str) -> str:
    """Source with non-code spans blanked, offsets preserved."""
    out: list[str] = []
    for kind, text in _scan(source):
        if kind == "code":
            out.append(text)
        else:
            out.append("".join("\n" if c == "\n" else " " for c in text))
    return "".join(out)


def find_function_boundaries(source) -> list[str]:
    """Return function names in source order (declarations + arrow consts).

    The search runs on masked code, so names that only appear inside
    strings, comments, regex literals, or template literals are not
    reported.
    """
    masked = _masked_code(_coerce_text(source))
    hits: list[tuple[int, str]] = []
    for pattern in (_FUNCTION_DECL, _ARROW_CONST):
        for match in pattern.finditer(masked):
            hits.append((match.start(), match.group(1)))
    hits.sort()
    return [name for _, name in hits]


def beautify_js(source) -> str:
    """Return an indented, line-broken rendering of JavaScript.

    Tokens are preserved: removing all whitespace from the output
    yields the same text as removing all whitespace from the input.
    """
    text_in = _coerce_text(source)
    lines: list[str] = []
    current: list[str] = []
    indent = 0
    paren_depth = 0

    def flush():
        text = "".join(current).strip()
        if text:
            lines.append("  " * indent + text)
        current.clear()

    for kind, token in _scan(text_in):
        if kind != "code":  # string / template / comment / regex chunk
            current.append(token)
            continue
        ch = token
        if ch == "(":
            paren_depth += 1
            current.append(ch)
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
            current.append(ch)
        elif ch == "{":
            current.append(" {")
            flush()
            indent += 1
        elif ch == "}":
            flush()
            indent = max(0, indent - 1)
            current.append("}")
            flush()
        elif ch == ";":
            if paren_depth > 0:
                # Inside a for(...) header or a call: not a line break.
                current.append(";")
            elif not "".join(current).strip() and lines:
                lines[-1] += ";"
            else:
                current.append(";")
                flush()
        elif ch in (" ", "\t", "\n", "\r"):
            if current and not "".join(current).endswith(" "):
                current.append(" ")
        else:
            current.append(ch)
    flush()
    return "\n".join(lines) + "\n"


# Name the example implementation used; kept so callers and the
# discovery-based tests find the same callable shape in core.
beautify = beautify_js


def lift_javascript(source, artifact_name: str = "minified.js") -> str:
    """Beautify JavaScript and stamp it as a Tier 2 lifted reconstruction."""
    header = (
        WATERMARK_JS
        + f"\n/* Lifted from: {artifact_name} - RECONSTRUCTION, not original source."
        + " Names destroyed by minification are not recovered. */\n"
    )
    return header + beautify_js(source)


lift_minified_js = lift_javascript
