"""Example GhostSlice plugin: a parser-lite slicer for Lua.

Copy this file into your project (or point --plugin at it) and name
it in the profile to teach GhostSlice a language it does not ship:

    .ghostslice.json:
        {"plugins": ["./tools/lua_slicer.py"]}

    or per run:
        ghostslice export . -o out --plugin ./tools/lua_slicer.py

This plugin uses the ATTRIBUTE style of the plugin contract (see
the README's "Plugins" section): the module-level LANGUAGE,
EXTENSIONS, slice_text, and outline below ARE the registration.
Plugins are ordinary Python code running with your full
privileges: only load plugins you have read and trust.

What it does (parser-lite, the same honesty level as GhostSlice's
built-in non-Python slicers):
  * "signatures": every function definition collapses to its
    definition line, a "-- ..." body marker, and its closing
    "end"; top-level statements (requires, table literals, calls)
    pass through untouched.
  * "interfaces": only the non-local (exported) function
    definitions, in the same collapsed form.
  * Any other mode: the source passes through unchanged.
  * outline(): the function definitions, so `ghostslice symbols`
    and `export --symbols` work for Lua files.

Function blocks are matched by counting block openers (function,
if/then, for/while/do, do, repeat/until) against `end`, over a
masked view of the source with string and comment contents blanked,
so a "function" inside a string or a comment never opens a block.
Long brackets ([[ ]] and [==[ ]==], string and comment forms) are
handled. What it does NOT do: parse expressions, resolve requires,
or understand metatables; a file it cannot match up degrades to
keeping the unmatched region verbatim rather than dropping code.
"""
from __future__ import annotations

import re

NAME = "Lua slicer (example plugin)"
LANGUAGE = "lua"
EXTENSIONS = [".lua"]


# -- masking: blank string/comment contents, keep the code -------

def _mask_lines(lines):
    """One masked line per input line: string and comment contents
    replaced by spaces. State (long string / long comment) carries
    across lines; short strings and line comments do not."""
    masked = []
    long_level = None  # '=' count of the open long bracket, or None
    for line in lines:
        out = []
        i, n = 0, len(line)
        quote = None  # open short-string quote on THIS line
        while i < n:
            if long_level is not None:
                close = "]" + "=" * long_level + "]"
                j = line.find(close, i)
                if j == -1:
                    out.append(" " * (n - i))
                    i = n
                else:
                    out.append(" " * (j + len(close) - i))
                    i = j + len(close)
                    long_level = None
                continue
            if quote is not None:
                ch = line[i]
                out.append(" ")
                if ch == "\\" and i + 1 < n:
                    out.append(" ")
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                i += 1
                continue
            if line.startswith("--", i):
                rest = line[i + 2:]
                m = re.match(r"\[(=*)\[", rest)
                if m:  # long comment --[[ ]] / --[==[ ]==]
                    long_level = len(m.group(1))
                    out.append(" " * (2 + m.end()))
                    i += 2 + m.end()
                else:  # line comment: blank to end of line
                    out.append(" " * (n - i))
                    i = n
                continue
            ch = line[i]
            if ch in "'\"":
                quote = ch
                out.append(" ")
                i += 1
                continue
            m = re.match(r"\[(=*)\[", line[i:])
            if m:  # long string [[ ]] / [==[ ]==]
                long_level = len(m.group(1))
                out.append(" " * m.end())
                i += m.end()
                continue
            out.append(ch)
            i += 1
        masked.append("".join(out))
    return masked


# -- block matching ----------------------------------------------

_TOKEN_RE = re.compile(
    r"\b(function|elseif|if|then|for|while|do|repeat|until|end)\b")
_DEF_RES = (
    (re.compile(r"^\s*local\s+function\s+([A-Za-z_][\w.:]*)\s*\("), True),
    (re.compile(r"^\s*function\s+([A-Za-z_][\w.:]*)\s*\("), False),
    (re.compile(r"^\s*local\s+([A-Za-z_][\w.]*)\s*=\s*function\s*\("), True),
    (re.compile(r"^\s*([A-Za-z_][\w.]*)\s*=\s*function\s*\("), False),
)


def _def_on_line(masked_line):
    """(qualified_name, is_local) when this line DEFINES a function,
    else (None, False). Anonymous functions return (None, False)
    too: they still open a block, they just have no name."""
    for rx, is_local in _DEF_RES:
        m = rx.match(masked_line)
        if m:
            return m.group(1), is_local
    return None, False


def _functions(masked):
    """Function spans over masked lines: [{name, local, start, end}]
    with 0-based inclusive line numbers. A function whose matching
    `end` is never found is dropped (its text degrades to verbatim),
    never guessed."""
    funcs = []
    stack = []  # (kind, record-or-None); kinds: function/if/loop/do/repeat
    pending_if = False
    skip_then = False  # an elseif's `then` opens nothing
    pending_loop = False
    for idx, line in enumerate(masked):
        for m in _TOKEN_RE.finditer(line):
            if m.start() > 0 and line[m.start() - 1] in ".:":
                continue  # a field/method named like a keyword (t.end)
            tok = m.group(1)
            if tok == "function":
                name, is_local = _def_on_line(line)
                rec = {"name": name, "local": is_local,
                       "start": idx, "end": None}
                stack.append(("function", rec))
                funcs.append(rec)
            elif tok == "if":
                pending_if = True
            elif tok == "elseif":
                skip_then = True
            elif tok == "then":
                if skip_then:
                    skip_then = False
                elif pending_if:
                    stack.append(("if", None))
                    pending_if = False
            elif tok in ("for", "while"):
                pending_loop = True
            elif tok == "do":
                stack.append(("loop" if pending_loop else "do", None))
                pending_loop = False
            elif tok == "repeat":
                stack.append(("repeat", None))
            elif tok == "until":
                if stack and stack[-1][0] == "repeat":
                    stack.pop()
            elif tok == "end":
                if stack:
                    kind, rec = stack.pop()
                    if kind == "function" and rec is not None:
                        rec["end"] = idx
    return [f for f in funcs if f["end"] is not None]


# -- rendering -----------------------------------------------------

def _render(lines, funcs, keep):
    """Collapse each kept function span to def line + marker + end;
    drop the spans `keep` rejects; pass everything else through."""
    by_start = {f["start"]: f for f in funcs}
    out = []
    i, n = 0, len(lines)
    while i < n:
        f = by_start.get(i)
        if f is None:
            out.append(lines[i])
            i += 1
            continue
        if keep(f):
            out.append(lines[f["start"]])
            if f["end"] > f["start"]:
                out.append("    -- ...")
                out.append(lines[f["end"]])
        i = f["end"] + 1
    return "\n".join(out) + ("\n" if out else "")


def slice_text(path, text, mode):
    """The plugin contract's slicer. Modes this plugin does not
    implement return the text unchanged (GhostSlice's core handles
    'full' and 'exclude' before a plugin is ever called)."""
    if mode not in ("signatures", "interfaces"):
        return text
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    funcs = _functions(_mask_lines(lines))
    if mode == "signatures":
        return _render(lines, funcs, lambda f: True)
    return _render(lines, funcs,
                   lambda f: f["name"] is not None and not f["local"])


def outline(path, text):
    """Function definitions as {name, kind, start, end} rows
    (0-based inclusive line spans), for `ghostslice symbols` and
    `export --symbols`. Methods (T:name) report kind "method" and
    the qualified name."""
    lines = text.split("\n")
    rows = []
    for f in _functions(_mask_lines(lines)):
        if f["name"] is None:
            continue
        qualified = f["name"]
        short = re.split(r"[.:]", qualified)[-1]
        rows.append({
            "name": short,
            "qualified": qualified,
            "kind": "method" if ":" in qualified else "function",
            "start": f["start"],
            "end": f["end"],
        })
    return rows
