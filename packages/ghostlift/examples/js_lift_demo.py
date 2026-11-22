"""Reference minified-JS lift used by the GhostLift examples and tests.

This is an *example* implementation that lives under ``examples/`` on
purpose. It is not the GhostLift core (the core package is
``src/ghostlift/``, and its CLI now lifts minified JS as Tier 2
directly). It exists so the Tier-2 JS behaviour described in README.md
has something concrete and testable:

* beautify: put minified JavaScript back into indented, line-broken
  form without changing the tokens, tracking string literals and
  comments so braces and semicolons inside strings do not break it;
* find function boundaries: report named function declarations and
  ``const name = (...) =>`` arrow functions, in source order.

Limits, stated plainly: regular-expression literals and template
literals with nested ``${...}`` expressions can confuse the simple
scanner. Fixtures for this demo avoid regex literals. The core tool
must label its own limits the same way.

Stdlib only. Static text work only: this module never runs the
JavaScript it lifts.
"""

from __future__ import annotations

import re

WATERMARK_JS = "/* ghostlift: lifted tier=2 source=minified-js reconstruction=structured */"

_FUNCTION_DECL = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")
_ARROW_CONST = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")


def _mask_strings_and_comments(source: str) -> str:
    """Blank out string/comment chunks, preserving offsets and length.

    Reuses the tokenizer beautify() already trusts, so the boundary
    scan below sees the same strings and comments beautify sees,
    instead of regex-matching the raw text (which reported
    ``function fake()`` inside a string literal, or a commented-out
    declaration, as a real boundary).
    """
    masked: list[str] = []
    for token in _tokens(source):
        if token.startswith(('"', "'", "`", "//", "/*")):
            masked.append(" " * len(token))
        else:
            masked.append(token)
    return "".join(masked)


def find_function_boundaries(source: str) -> list[str]:
    """Return function names in source order (declarations + arrow consts)."""
    masked = _mask_strings_and_comments(source)
    hits: list[tuple[int, str]] = []
    for pattern in (_FUNCTION_DECL, _ARROW_CONST):
        for match in pattern.finditer(masked):
            hits.append((match.start(), match.group(1)))
    hits.sort()
    return [name for _, name in hits]


def _tokens(source: str):
    """Yield characters, keeping string/comment spans intact as chunks."""
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == ch:
                    j += 1
                    break
                j += 1
            yield source[i:j]
            i = j
        elif source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j == -1 else j
            yield source[i:j]
            i = j
        elif source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j == -1 else j + 2
            yield source[i:j]
            i = j
        else:
            yield ch
            i += 1


def beautify(source: str) -> str:
    """Return an indented, line-broken rendering of minified JS.

    Tokens are preserved: removing all whitespace from the output
    yields the same text as removing all whitespace from the input
    for the fixture class this demo targets (no regex literals).
    """
    lines: list[str] = []
    current: list[str] = []
    indent = 0

    def flush():
        text = "".join(current).strip()
        if text:
            lines.append("  " * indent + text)
        current.clear()

    for token in _tokens(source):
        if len(token) > 1:  # string or comment chunk
            current.append(token)
            continue
        ch = token
        if ch == "{":
            current.append(" {")
            flush()
            indent += 1
        elif ch == "}":
            flush()
            indent = max(0, indent - 1)
            current.append("}")
            flush()
        elif ch == ";":
            if not "".join(current).strip() and lines:
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


def lift_minified_js(source: str, original: str = "app.min.js") -> str:
    """Beautify and watermark minified JS, the Tier-2 example path.

    The output is the ``WATERMARK_JS`` comment line followed by the
    beautified source. ``original`` names the artifact the source
    came from; it is accepted for symmetry with the other example
    lifters and does not change the watermark text.
    """
    header = WATERMARK_JS.replace("app.min.js", original) if original != "app.min.js" else WATERMARK_JS
    return header + "\n" + beautify(source)


if __name__ == "__main__":  # pragma: no cover - manual demo entry
    import pathlib
    import sys

    path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).with_name("minified_demo") / "app.min.js"
    print(lift_minified_js(path.read_text(), original=path.name), end="")
    print("// functions:", ", ".join(find_function_boundaries(path.read_text())))
