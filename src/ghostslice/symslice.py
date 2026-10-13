"""Symbol-level slicing (v0.18): slice to named symbols, not files.

Two surfaces:

- Outlines: for every language the slicer handles, a list of the
  symbols a file defines — name, qualified name, kind, and the line
  span the symbol occupies. Python outlines come from `ast` (exact:
  nested functions, methods, classes, module constants and class
  attributes all appear, with decorator-aware spans). The other
  languages reuse the slicer's own parser-lite machinery (the same
  declaration regexes and the string/comment-aware brace matcher),
  so an outline span is exactly the span the signatures slicer
  already trusts. Languages with no outline (notebook, markdown,
  config/data, plain text) report None — never a guessed outline.

- Selection + rendering: `resolve_symbol_selection` matches a spec
  list (bare names, `Class.method` qualified names, `file.py:name`
  scoping, `*` globs) against the outlines of a whole scan. A bare
  name that matches in several files matches in ALL of them (the
  report says so — ambiguity is printed, never silently resolved).
  A spec that matches nothing is an error with near-miss
  suggestions: a typo must not silently export less context.

Rendering (`slice_with_symbols`): a matched file contributes the
requested symbols WITH bodies, plus always-context — imports, and
(for Python) the module docstring's first line and small module
constants, mirroring signatures mode. Symbols that were not
requested collapse: Python reuses the signatures renderers
(`_func_signature` / `_class_signature`); lite languages collapse
functions/methods to their signature line and keep declaration
types (interface/struct/enum/trait/protocol/record, TS types) whole,
exactly as signatures mode treats them. A container (class) with a
requested descendant renders as a shell: header, rendered children,
closing line. Module constants/values are always-context in lite
languages too.

Lite limits, honestly: nested functions are outlined only for
Python (lite outlines are top-level plus class members); methods
of declaration types (interfaces, traits, protocols) are listed
and selectable, but selecting one ships the whole type —
declaration types are surface, exactly as in signatures mode.
Constructors are not selectable symbols in lite languages; C#
namespaces do not prefix qualified names; Go grouped
`type ( ... )` declarations are not outlined; Kotlin/Swift
single-expression function bodies that continue on more-indented
lines are part of the symbol only on their first line; and a C++
out-of-line definition (`int Store::total() { ... }`) is its own
symbol, spelled as written, separate from the in-class
declaration it implements.
"""
from __future__ import annotations

import ast
import difflib
import fnmatch
import re
from dataclasses import dataclass

from .scanner import language_for
from .slicer import (
    _ACCESS_RE, _ARROW_RE, _CLASS_RE, _CPP_CLASS_RE, _CPP_ENUM_RE,
    _CPP_NS_RE, _C_TYPE_RE, _ENUM_RE,
    _EXTRA_CFG, _FUNCTION_RE, _GO_TYPE_RE, _IMPORT_LINE_RES, _IMPORT_RE,
    _INTERFACE_RE, _JV_TYPE_RE, _METHOD_RE, _PREPROC_RE, _RB_ATTR_RE,
    _RB_CONST_RE, _RB_DEF_RE, _RB_REQUIRE_RE, _RB_TYPE_RE, _RS_FN_RE,
    _RS_IMPL_RE, _RS_TYPE_RE, _SC_ALIAS_RE, _SC_IMPORT_RE,
    _SC_TYPE_RE, _SC_VAL_RE, _TYPE_RE, _block_end, _body_brace_col,
    _brace_end, _class_signature, _c_func_head, _c_head_end, _c_sig_text,
    _c_type_block, _doc_first_line, _extra_block_end, _find_block_brace,
    _func_signature, _indent_block_end, _is_type_alias, _lite_is_func,
    _mask_quotes, _rb_block_end, _scala_def, _sig_before_body,
    _statement_end,
)

OUTLINE_LANGUAGES = frozenset({
    "python", "typescript", "javascript", "go", "rust", "java",
    "csharp", "php", "ruby", "kotlin", "swift", "c", "cpp", "scala",
})

# Kinds that render verbatim even when not selected: declaration
# surface (the signatures-mode rule) and plain data (always-context).
_VERBATIM_KINDS = ("type", "constant", "value", "attribute")
_CONTAINER_KINDS = ("class", "impl", "namespace")


@dataclass
class Symbol:
    name: str            # bare name, e.g. "login"
    qualified: str       # e.g. "Auth.login", "Store::total"
    kind: str            # function|method|class|type|constant|value|attribute
    start: int           # 0-based first line of the span (incl. annotations)
    end: int             # 0-based last line of the span (inclusive)
    head_end: int        # 0-based last line of the declaration head
    decl: int            # 0-based line of the declaration itself
    parent: str | None = None       # qualified name of the enclosing symbol
    selectable: bool = True         # containers like impl/namespace are not

    def span_text(self, lines: list[str]) -> str:
        return "\n".join(lines[self.start:self.end + 1])


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _decl_start(lines: list[str], i: int) -> int:
    """Extend a declaration line upward over contiguous annotation /
    attribute lines (`@Override`, `#[test]`, `@decorator`)."""
    start = i
    while start - 1 >= 0:
        prev = lines[start - 1].strip()
        if prev.startswith("@") or prev.startswith("#["):
            start -= 1
        else:
            break
    return start


def _template_start(lines: list[str], i: int) -> int:
    """C++: a `template <...>` head on its own line belongs to the span."""
    if i - 1 >= 0:
        prev = lines[i - 1].strip()
        if prev.startswith("template <") or prev.startswith("template<"):
            return i - 1
    return i


def _stmt_end(lines: list[str], i: int, end: int, limit: int = 8) -> int:
    """Bounded statement end: first following line ending in `;`."""
    for t in range(i, min(i + limit, end)):
        if lines[t].rstrip().endswith(";"):
            return t
    return i


def _paren_end(lines: list[str], i: int, end: int) -> int:
    """Line where the parens opened at/after line `i` balance out."""
    depth = 0
    seen = False
    for t in range(i, min(end, i + 13)):
        for ch in lines[t]:
            if ch == "(":
                depth += 1
                seen = True
            elif ch == ")":
                depth -= 1
        if seen and depth <= 0:
            return t
    return i


def _brace_line_in(lines: list[str], i: int, end: int) -> int:
    for t in range(i, end + 1):
        if "{" in lines[t]:
            return t
    return i


def _name_after(line: str, keywords: tuple[str, ...]) -> str | None:
    m = re.search(r"\b(?:" + "|".join(keywords) + r")\s+([A-Za-z_$][\w$]*)", line)
    return m.group(1) if m else None


def _method_name(line: str) -> str | None:
    """The identifier directly before the first `(` on a member line.

    Modifiers and return types are never followed by `(`, so the
    first identifier that is is the member name (getters included:
    `get` is followed by the property name, not a paren)."""
    m = re.search(r"([A-Za-z_$][\w$]*)\s*\(", line)
    return m.group(1) if m else None


# Member *declarations* (interface bodies): same shape as a method
# head but ending in `;` instead of a body brace.
_MEMBER_DECL_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|async|readonly|abstract"
    r"|override)\s+)*(?:get\s+|set\s+)?([A-Za-z_$][\w$]*)\s*\(")


# ---------------------------------------------------------------------------
# Python outline (ast, exact) + unparseable-file fallback
# ---------------------------------------------------------------------------

def _target_names(target) -> list[str]:
    """Simple names bound by an assignment target (tuple/list/starred)."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in target.elts:
            out.extend(_target_names(elt))
        return out
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []  # Attribute/Subscript targets bind no new simple name


def _py_mk(node, name: str, qualified: str, kind: str,
           parent: str | None) -> Symbol:
    start = node.lineno
    for dec in getattr(node, "decorator_list", []):
        start = min(start, dec.lineno)
    return Symbol(name=name, qualified=qualified, kind=kind,
                  start=start - 1, end=(node.end_lineno or node.lineno) - 1,
                  head_end=node.lineno - 1, decl=node.lineno - 1,
                  parent=parent)


def _py_outline(source: str) -> list[Symbol]:
    try:
        tree = ast.parse(source)
    except Exception:
        return _py_fallback_outline(source.splitlines())
    out: list[Symbol] = []

    def visit(node, prefix: str, parent_kind: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{prefix}.{child.name}" if prefix else child.name
                kind = "method" if parent_kind == "class" else "function"
                out.append(_py_mk(child, child.name, q, kind, prefix or None))
                visit(child, q, "function")
            elif isinstance(child, ast.ClassDef):
                q = f"{prefix}.{child.name}" if prefix else child.name
                out.append(_py_mk(child, child.name, q, "class", prefix or None))
                visit(child, q, "class")
            elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                # Constants/attributes are definitions at module and
                # class level only; function locals are not symbols.
                if parent_kind in (None, "class"):
                    targets = child.targets if isinstance(child, ast.Assign) \
                        else [child.target]
                    kind = "constant" if parent_kind is None else "attribute"
                    for target in targets:
                        for name in _target_names(target):
                            q = f"{prefix}.{name}" if prefix else name
                            out.append(_py_mk(child, name, q, kind,
                                              prefix or None))
            else:
                # Compound statements (if/try/with/...): definitions
                # inside them belong to the same enclosing scope.
                visit(child, prefix, parent_kind)

    visit(tree, "", None)
    out.sort(key=lambda s: (s.start, -s.end))
    return out


_PY_DEF_LINE_RE = re.compile(r"^(\s*)(async\s+def|def|class)\s+([A-Za-z_]\w*)")


def _py_fallback_outline(lines: list[str]) -> list[Symbol]:
    """Outline for Python that does not parse: def/class lines only,
    spans by indentation (a span can over-claim a tail of its parent
    body — this path is a fallback, and it says so in the README)."""
    defs: list[tuple[int, int, str, str]] = []
    for i, line in enumerate(lines):
        m = _PY_DEF_LINE_RE.match(line)
        if m:
            defs.append((i, len(m.group(1)), m.group(2), m.group(3)))
    out: list[Symbol] = []
    built: list[tuple[int, Symbol]] = []  # (indent, symbol) in order
    for k, (i, indent, kw, name) in enumerate(defs):
        end = len(lines) - 1
        for (j, ind2, _kw2, _n2) in defs[k + 1:]:
            if ind2 <= indent:
                end = j - 1
                break
        while end > i and not lines[end].strip():
            end -= 1
        parent_q = None
        parent_kind = None
        for ind2, sym in reversed(built):
            if ind2 < indent:
                parent_q = sym.qualified
                parent_kind = sym.kind
                break
        q = f"{parent_q}.{name}" if parent_q else name
        if kw == "class":
            kind = "class"
        elif parent_kind == "class":
            kind = "method"
        else:
            kind = "function"
        sym = Symbol(name=name, qualified=q, kind=kind, start=i, end=end,
                     head_end=i, decl=i, parent=parent_q)
        out.append(sym)
        built.append((indent, sym))
    return out


# ---------------------------------------------------------------------------
# TypeScript / JavaScript outline (parser-lite spans)
# ---------------------------------------------------------------------------

def _ts_outline(lines: list[str]) -> list[Symbol]:
    out: list[Symbol] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _IMPORT_RE.match(line):
            i += 1
            continue
        if _INTERFACE_RE.match(line) or _ENUM_RE.match(line) \
                or (_TYPE_RE.match(line) and "{" in line):
            name = _name_after(line, ("interface", "enum", "type"))
            end = _brace_end(lines, i, body_col=line.find("{")) if "{" in line else i
            if name:
                out.append(Symbol(name, name, "type", i, end, i, i))
                if _INTERFACE_RE.match(line) and end > i:
                    # Interface method declarations are symbols too
                    # (the interface itself renders whole). Member
                    # declarations end in `;`, so the class-body
                    # _METHOD_RE (which wants a body brace) cannot
                    # see them; use a declaration-shaped pattern.
                    j = i + 1
                    while j < end:
                        mm = _MEMBER_DECL_RE.match(lines[j])
                        if mm and mm.group(1) != "constructor":
                            mend = _paren_end(lines, j, end)
                            out.append(Symbol(
                                mm.group(1), f"{name}.{mm.group(1)}",
                                "method", j, mend, mend, j, parent=name))
                            j = mend + 1
                            continue
                        j += 1
            i = end + 1
            continue
        if _TYPE_RE.match(line):
            name = _name_after(line, ("type",))
            end = _statement_end(lines, i)
            if name:
                out.append(Symbol(name, name, "type", i, end, i, i))
            i = end + 1
            continue
        cm = _CLASS_RE.match(line)
        if cm:
            name = _name_after(line, ("class",))
            end = _brace_end(lines, i, body_col=line.find("{"))
            if name:
                out.append(Symbol(name, name, "class", _decl_start(lines, i),
                                  end, _brace_line_in(lines, i, end), i))
                j = i + 1
                while j < end:
                    l2 = lines[j]
                    if _METHOD_RE.match(l2):
                        mname = _method_name(l2)
                        if mname and mname != "constructor":
                            mend = _brace_end(
                                lines, j, body_col=_body_brace_col(l2)) \
                                if "{" in l2 else j
                            out.append(Symbol(
                                mname, f"{name}.{mname}", "method",
                                _decl_start(lines, j), mend, j, j,
                                parent=name))
                            j = mend + 1
                            continue
                    j += 1
            i = end + 1
            continue
        if _FUNCTION_RE.match(line):
            name = _name_after(line, ("function",))
            end = _brace_end(lines, i, body_col=_body_brace_col(line)) \
                if "{" in line else i
            if name:
                out.append(Symbol(name, name, "function",
                                  _decl_start(lines, i), end, i, i))
            i = end + 1
            continue
        if _ARROW_RE.match(line):
            m = re.search(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)", line)
            name = m.group(1) if m else None
            if "{" in line:
                end = _brace_end(lines, i, body_col=_body_brace_col(line))
            else:
                end = _statement_end(lines, i)
            if name:
                out.append(Symbol(name, name, "function", i, end, i, i))
            i = end + 1
            continue
        m = re.match(r"^\s*(export\s+)?(const|let|var)\s+([A-Za-z_$][\w$]*)",
                     line)
        if m:
            if "{" in line and not line.rstrip().endswith(";"):
                end = _brace_end(lines, i, body_col=line.find("{"))
            else:
                end = _statement_end(lines, i)
            out.append(Symbol(m.group(3), m.group(3), "constant", i, end, i, i))
            i = end + 1
            continue
        i += 1
    return out


# ---------------------------------------------------------------------------
# Go / Rust / Java / C# outlines (parser-lite spans)
# ---------------------------------------------------------------------------

def _go_outline(lines: list[str]) -> list[Symbol]:
    out: list[Symbol] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = re.match(r"^\s*func\s+(?:\(([^)]*)\)\s*)?([A-Za-z_]\w*)\s*\(",
                     line)
        if m:
            recv, name = m.group(1), m.group(2)
            end = _block_end(lines, i, "go") if "{" in line \
                else _paren_end(lines, i, n)
            if recv:
                rtype = recv.strip().split()[-1].lstrip("*").split("[")[0]
                out.append(Symbol(name, f"{rtype}.{name}", "method", i, end,
                                  _paren_end(lines, i, n), i, parent=rtype))
            else:
                out.append(Symbol(name, name, "function", i, end,
                                  _paren_end(lines, i, n), i))
            i = end + 1
            continue
        tm = re.match(r"^\s*type\s+([A-Za-z_]\w*)\b", line)
        if tm:
            name = tm.group(1)
            end = _block_end(lines, i, "go") if "{" in line else i
            out.append(Symbol(name, name, "type", i, end, i, i))
            gm = _GO_TYPE_RE.match(line)
            if gm and gm.group(1) == "interface" and end > i:
                # Interface methods are separate symbols (Go interfaces
                # carry no bodies; the declaration IS the symbol).
                j = i + 1
                while j < end:
                    mm = re.match(r"^\s*([A-Za-z_]\w*)\s*\(", lines[j])
                    if mm:
                        mend = _paren_end(lines, j, end)
                        out.append(Symbol(mm.group(1), f"{name}.{mm.group(1)}",
                                          "method", j, mend, mend, j,
                                          parent=name))
                        j = mend + 1
                        continue
                    j += 1
            i = end + 1
            continue
        i += 1
    return out


def _rust_impl_type(line: str) -> str:
    s = re.sub(r"^\s*(unsafe\s+)?impl\b", "", line).strip()
    s = re.sub(r"<[^>]*>", "", s)
    if " for " in s:
        s = s.split(" for ")[-1]
    parts = s.split()
    return parts[0].split("<")[0].strip() if parts else ""


def _rust_region(lines: list[str], i0: int, end: int,
                 parent_q: str | None, out: list[Symbol]) -> None:
    i = i0
    while i < end:
        line = lines[i]
        if _RS_IMPL_RE.match(line) and "{" in line:
            bend = _block_end(lines, i, "rust")
            tname = _rust_impl_type(line)
            if tname:
                out.append(Symbol(tname, tname, "impl", i, bend, i, i,
                                  parent=parent_q, selectable=False))
                _rust_region(lines, i + 1, bend, tname, out)
            i = bend + 1
            continue
        tm = _RS_TYPE_RE.match(line)
        if tm:
            km = re.search(r"\b(struct|enum|trait|union)\s+([A-Za-z_]\w*)",
                           line)
            if km:
                bend = _block_end(lines, i, "rust") if "{" in line \
                    else _stmt_end(lines, i, end)
                out.append(Symbol(km.group(2), km.group(2), "type",
                                  _decl_start(lines, i), bend, i, i,
                                  parent=parent_q))
                if km.group(1) == "trait" and bend > i:
                    # Trait method declarations/default bodies are
                    # symbols too (the trait itself renders whole).
                    _rust_region(lines, i + 1, bend, km.group(2), out)
                i = bend + 1
                continue
        if _RS_FN_RE.match(line):
            fm = re.search(r"\bfn\s+([A-Za-z_]\w*)", line)
            if fm:
                name = fm.group(1)
                bend = _block_end(lines, i, "rust") if "{" in line \
                    else _stmt_end(lines, i, end)
                q = f"{parent_q}.{name}" if parent_q else name
                out.append(Symbol(name, q, "method" if parent_q else "function",
                                  _decl_start(lines, i), bend,
                                  _paren_end(lines, i, end), i,
                                  parent=parent_q))
                i = bend + 1
                continue
        i += 1


def _jv_region(lines: list[str], i0: int, end: int, lang: str,
               parent_q: str | None, out: list[Symbol]) -> None:
    i = i0
    while i < end:
        line = lines[i]
        tm = _JV_TYPE_RE.match(line)
        if tm:
            kind_word = tm.group(2)
            nm = re.search(r"\b(?:class|interface|enum|record|struct)\s+"
                           r"([A-Za-z_]\w*)", line)
            if nm:
                name = nm.group(1)
                is_decl = kind_word in ("interface", "enum", "record")
                bend = _block_end(lines, i, lang) if "{" in line \
                    else _stmt_end(lines, i, end)
                q = f"{parent_q}.{name}" if parent_q else name
                out.append(Symbol(name, q, "type" if is_decl else "class",
                                  _decl_start(lines, i), bend,
                                  _brace_line_in(lines, i, bend), i,
                                  parent=parent_q))
                if bend > i and (not is_decl or kind_word == "interface"):
                    # Interface method declarations are symbols too
                    # (the interface itself renders whole).
                    _jv_region(lines, i + 1, bend, lang, q, out)
                i = bend + 1
                continue
        if parent_q and _lite_is_func(line, lang):
            name = _method_name(line)
            if name and name != parent_q.split(".")[-1]:  # not a constructor
                bend = _block_end(lines, i, lang) if "{" in line \
                    else _stmt_end(lines, i, end)
                out.append(Symbol(name, f"{parent_q}.{name}", "method",
                                  _decl_start(lines, i), bend,
                                  _paren_end(lines, i, end), i,
                                  parent=parent_q))
                i = bend + 1
                continue
        i += 1


# ---------------------------------------------------------------------------
# PHP / Kotlin / Swift outline (parser-lite spans)
# ---------------------------------------------------------------------------

_EXTRA_NAME_RES = {
    "php": re.compile(r"(?:class|interface|trait|enum)\s+(\w+)"),
    "kotlin": re.compile(r"(?:class|interface|object)\s+`?(\w+)`?"),
    "swift": re.compile(r"(?:class|struct|protocol|enum|extension|actor)"
                        r"\s+(\w+)"),
}

_EXTRA_PROP_NAME_RES = {
    "php": re.compile(r"\$(\w+)"),
    "kotlin": re.compile(r"\b(?:val|var)\s+`?(\w+)`?"),
    "swift": re.compile(r"\b(?:var|let)\s+(\w+)"),
}


def _indent_continuation(lines: list[str], i: int, end: int) -> int:
    """Last line of an expression body continuing by indentation."""
    base = len(lines[i]) - len(lines[i].lstrip())
    j = i
    while j + 1 < end:
        nxt = lines[j + 1]
        if not nxt.strip():
            break
        if len(nxt) - len(nxt.lstrip()) > base:
            j += 1
        else:
            break
    return j


def _extra_region(lines: list[str], i0: int, end: int, lang: str,
                  parent_q: str | None, out: list[Symbol]) -> None:
    cfg = _EXTRA_CFG[lang]
    i = i0
    while i < end:
        line = lines[i]
        tm = cfg["type"].match(line)
        if tm:
            kind_word = tm.group(2)
            nm = _EXTRA_NAME_RES[lang].search(line)
            if nm:
                name = nm.group(1)
                is_decl = kind_word in cfg["full_kinds"]
                found = _find_block_brace(lines, i, limit=3)
                if found:
                    bl, bcol = found
                    bend = _brace_end(lines, bl, body_col=bcol, lang=lang)
                    head_end = bl
                else:
                    bend = i
                    head_end = i
                q = f"{parent_q}.{name}" if parent_q else name
                out.append(Symbol(name, q, "type" if is_decl else "class",
                                  _decl_start(lines, i), bend, head_end, i,
                                  parent=parent_q))
                if bend > i:
                    # Classes/objects recurse for members; declaration
                    # types (interface/trait/protocol) recurse too —
                    # their method declarations are symbols (the type
                    # itself renders whole).
                    _extra_region(lines, i + 1, bend, lang, q, out)
                i = bend + 1
                continue
        if cfg["func"].match(line):
            fm = cfg["func_name"].search(line)
            if fm:
                name = fm.group(1)
                if "{" in line:
                    bend = _extra_block_end(lines, i, lang)
                elif lang == "php":
                    bend = _stmt_end(lines, i, end)
                else:  # kotlin/swift single-expression body
                    bend = _indent_continuation(lines, i, end)
                q = f"{parent_q}.{name}" if parent_q else name
                out.append(Symbol(name, q,
                                  "method" if parent_q else "function",
                                  _decl_start(lines, i), bend,
                                  _paren_end(lines, i, end), i,
                                  parent=parent_q))
                i = bend + 1
                continue
        if cfg["prop"] and cfg["prop"].match(line):
            # Properties/fields are symbols too (audit G13 F2): the
            # signatures slicers keep them and task selection counts
            # them, so an export must be able to name them. They
            # render verbatim (data is always-context).
            nm = _EXTRA_PROP_NAME_RES[lang].search(line)
            if nm:
                name = nm.group(1)
                if "{" in line:  # computed property / accessor block
                    bend = _extra_block_end(lines, i, lang)
                elif lang == "php":
                    bend = _stmt_end(lines, i, end)
                else:
                    bend = i
                q = f"{parent_q}.{name}" if parent_q else name
                out.append(Symbol(name, q,
                                  "attribute" if parent_q else "constant",
                                  i, bend, i, i, parent=parent_q))
                i = bend + 1
                continue
        i += 1


# ---------------------------------------------------------------------------
# Ruby outline (keyword/end spans)
# ---------------------------------------------------------------------------

_RB_DEF_NAME_RE = re.compile(r"def\s+(?:(\w[\w:]*)\.)?([\w!?=<>+\-*\[\]]+)")


def _rb_region(lines: list[str], i0: int, end: int,
               parent_q: str | None, out: list[Symbol]) -> None:
    i = i0
    while i < end:
        line = lines[i]
        tm = _RB_TYPE_RE.match(line)
        if tm:
            nm = re.search(r"(?:module|class)\s+([\w:]+)", line)
            if nm:
                written = nm.group(1)
                bend = _rb_block_end(lines, i)
                if parent_q and "::" not in written:
                    q = f"{parent_q}::{written}"
                else:
                    q = written
                out.append(Symbol(written.split("::")[-1], q, "class", i,
                                  bend, i, i, parent=parent_q))
                _rb_region(lines, i + 1, bend, q, out)
                i = bend + 1
                continue
        if _RB_DEF_RE.match(line):
            dm = _RB_DEF_NAME_RE.search(line)
            if dm:
                owner, bare = dm.group(1), dm.group(2)
                bend = _rb_block_end(lines, i)
                if owner == "self" and parent_q:
                    q = f"{parent_q}.{bare}"
                    par = parent_q
                elif owner:
                    q = f"{owner}.{bare}"
                    par = owner
                elif parent_q:
                    q = f"{parent_q}.{bare}"
                    par = parent_q
                else:
                    q = bare
                    par = None
                out.append(Symbol(bare, q, "method" if par else "function",
                                  i, bend, i, i, parent=par))
                i = bend + 1
                continue
        i += 1


# ---------------------------------------------------------------------------
# C / C++ outline (parser-lite spans, qualified names)
# ---------------------------------------------------------------------------

def _c_qualified(lines: list[str], i: int, raw_name: str,
                 prefix: str, owner: str | None) -> str:
    masked = _mask_quotes(lines[i])
    m = re.search(r"([A-Za-z_][\w:]*::)\s*" + re.escape(raw_name) + r"\s*\(",
                  masked)
    if m:
        return m.group(1) + raw_name
    if owner:
        return f"{owner}::{raw_name}"
    return prefix + raw_name


def _c_region(lines: list[str], i0: int, end: int, lang: str,
              prefix: str, owner: str | None, out: list[Symbol]) -> None:
    i = i0
    pp_cont = False
    while i < end:
        line = lines[i]
        masked = _mask_quotes(line)
        if pp_cont or _PREPROC_RE.match(line):
            pp_cont = line.rstrip().endswith("\\")
            i += 1
            continue
        pp_cont = False
        if lang == "cpp" and owner is None:
            nm = _CPP_NS_RE.match(masked)
            if nm and not masked.rstrip().endswith(";"):
                found = _find_block_brace(lines, i)
                if found is not None:
                    bl, bcol = found
                    bend = _brace_end(lines, bl, body_col=bcol, lang="cpp")
                    nsname = nm.group(2) or nm.group(5) or ""
                    if nsname:
                        out.append(Symbol(nsname, prefix + nsname, "namespace",
                                          i, bend, bl, i, selectable=False))
                    _c_region(lines, bl + 1, bend, lang,
                              prefix + (f"{nsname}::" if nsname else ""),
                              None, out)
                    i = bend + 1
                    continue
            cm = _CPP_CLASS_RE.match(masked)
            if cm:
                cname = cm.group(2)
                found = _find_block_brace(lines, i)
                if found is None:
                    i = _stmt_end(lines, i, end) + 1
                    continue
                bl, bcol = found
                bend = _brace_end(lines, bl, body_col=bcol, lang="cpp")
                q = f"{owner}::{cname}" if owner else prefix + cname
                out.append(Symbol(cname, q, "class",
                                  _template_start(lines, i), bend, bl, i,
                                  parent=owner))
                _c_region(lines, bl + 1, bend, lang, "", q, out)
                i = bend + 1
                continue
            if _CPP_ENUM_RE.match(masked):
                tb = _c_type_block(lines, i, "cpp")
                if tb is not None:
                    _kind, tend = tb
                    em = re.search(r"enum\s+(?:class\s+|struct\s+)?"
                                   r"([A-Za-z_]\w*)", masked)
                    if em:
                        out.append(Symbol(em.group(1), prefix + em.group(1),
                                          "type", i, tend, i, i, parent=owner))
                    i = tend + 1
                    continue
        if lang == "c":
            tb = _c_type_block(lines, i, lang)
            if tb is not None:
                kind, tend = tb
                m = _C_TYPE_RE.match(masked)
                if kind == "block" and m and m.group(3):
                    out.append(Symbol(m.group(3), m.group(3), "type", i,
                                      tend, i, i))
                i = tend + 1
                continue
        bare = owner.split("::")[-1] if owner else None
        head = _c_func_head(lines, i, lang, bare_name=bare)
        if head is not None:
            nxt = _c_head_end(lines, head, lang)
            raw = head["name"]
            q = _c_qualified(lines, i, raw, prefix, owner)
            out.append(Symbol(raw.lstrip("~"), q,
                              "method" if owner else "function",
                              _template_start(lines, i), nxt - 1,
                              head["head_end"], i, parent=owner))
            i = nxt
            continue
        i += 1


# ---------------------------------------------------------------------------
# Scala outline (parser-lite spans)
# ---------------------------------------------------------------------------

def _scala_region_out(lines: list[str], i0: int, end: int,
                      parent_q: str | None, out: list[Symbol]) -> None:
    i = i0
    while i < end:
        line = lines[i]
        if _SC_IMPORT_RE.match(line):
            i += 1
            continue
        tm = _SC_TYPE_RE.match(line)
        if tm:
            kind_word, name = tm.group(1), tm.group(2)
            is_decl = kind_word in ("trait", "enum")
            found = _find_block_brace(lines, i, limit=4)
            if found is not None:
                bl, bcol = found
                bend = _brace_end(lines, bl, body_col=bcol, lang="scala")
                head_end = bl
                body_start = bl + 1
            else:
                bend = _indent_block_end(lines, i, end)
                head_end = i
                body_start = i + 1
            q = f"{parent_q}.{name}" if parent_q else name
            out.append(Symbol(name, q, "type" if is_decl else "class",
                              _decl_start(lines, i), bend, head_end, i,
                              parent=parent_q))
            if bend > i and (not is_decl or kind_word == "trait"):
                # Trait defs are symbols too (the trait renders whole).
                _scala_region_out(lines, body_start, bend, q, out)
            i = bend + 1
            continue
        if _SC_ALIAS_RE.match(line):
            am = _SC_ALIAS_RE.match(line)
            if am:
                name = am.group(1)
                q = f"{parent_q}.{name}" if parent_q else name
                out.append(Symbol(name, q, "type", i, i, i, i,
                                  parent=parent_q))
            i += 1
            continue
        d = _scala_def(lines, i, end)
        if d is not None:
            _sig, nxt, name = d
            if name:
                q = f"{parent_q}.{name}" if parent_q else name
                out.append(Symbol(name, q,
                                  "method" if parent_q else "function",
                                  _decl_start(lines, i), nxt - 1, i, i,
                                  parent=parent_q))
            i = nxt
            continue
        vm = _SC_VAL_RE.match(line)
        if vm:
            name = vm.group(2)
            masked = _mask_quotes(line)
            if "{" in masked:
                bend = _brace_end(lines, i, body_col=masked.find("{"),
                                  lang="scala")
            else:
                bend = i
            q = f"{parent_q}.{name}" if parent_q else name
            out.append(Symbol(name, q, "value", i, bend, i, i,
                              parent=parent_q))
            i = bend + 1
            continue
        i += 1


# ---------------------------------------------------------------------------
# Outline dispatch
# ---------------------------------------------------------------------------

def outline_source(source: str, language: str, path: str = "") -> list[Symbol] | None:
    """Symbols defined in one file, in source order.

    None when the language has no symbol outline (notebook, markdown,
    config/data languages, plain text); a list (possibly empty) for
    the languages in OUTLINE_LANGUAGES.
    """
    if language not in OUTLINE_LANGUAGES:
        return None
    lines = source.splitlines()
    if language == "python":
        return _py_outline(source)
    if language in ("typescript", "javascript"):
        return _ts_outline(lines)
    if language == "go":
        return _go_outline(lines)
    if language == "rust":
        out: list[Symbol] = []
        _rust_region(lines, 0, len(lines), None, out)
        return out
    if language in ("java", "csharp"):
        out = []
        _jv_region(lines, 0, len(lines), language, None, out)
        return out
    if language in ("php", "kotlin", "swift"):
        out = []
        _extra_region(lines, 0, len(lines), language, None, out)
        return out
    if language == "ruby":
        out = []
        _rb_region(lines, 0, len(lines), None, out)
        return out
    if language in ("c", "cpp"):
        out = []
        _c_region(lines, 0, len(lines), language, "", None, out)
        return out
    if language == "scala":
        out = []
        _scala_region_out(lines, 0, len(lines), None, out)
        return out
    return None


# ---------------------------------------------------------------------------
# Python rendering (ast): reuse the signatures renderers, keep bodies
# ---------------------------------------------------------------------------

def _segment(lines: list[str], node) -> str:
    start = node.lineno
    for dec in getattr(node, "decorator_list", []):
        start = min(start, dec.lineno)
    return "\n".join(lines[start - 1:(node.end_lineno or node.lineno)])


def _py_func_head(node, indent: str) -> list[str]:
    """Signature lines for a function WITHOUT the trailing `...`:
    the head of a shell whose kept children follow."""
    out: list[str] = []
    for dec in node.decorator_list:
        out.append(f"{indent}@{ast.unparse(dec)}")
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = ast.unparse(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    out.append(f"{indent}{prefix} {node.name}({args}){ret}:")
    doc = _doc_first_line(node)
    if doc:
        out.append(f'{indent}    """{doc}"""')
    return out


def _py_class_head(node, indent: str) -> list[str]:
    out: list[str] = []
    for dec in node.decorator_list:
        out.append(f"{indent}@{ast.unparse(dec)}")
    bases = [ast.unparse(b) for b in node.bases]
    bases += [f"{kw.arg}={ast.unparse(kw.value)}" for kw in node.keywords]
    head = f"{indent}class {node.name}"
    if bases:
        head += f"({', '.join(bases)})"
    head += ":"
    out.append(head)
    doc = _doc_first_line(node)
    if doc:
        out.append(f'{indent}    """{doc}"""')
    return out


def _has_kept_descendant(qualified: str, keep: set[str]) -> bool:
    prefix = qualified + "."
    return any(k.startswith(prefix) for k in keep)


_COMPOUND_WRAPPERS = tuple(
    t for t in (getattr(ast, "ExceptHandler", None),
                getattr(ast, "match_case", None))
    if t is not None)


def _compound_stmts(node):
    """Statements directly inside a compound statement, including
    those nested one level deeper in except handlers / match cases
    (which are not ast.stmt nodes themselves)."""
    for sub in ast.iter_child_nodes(node):
        if isinstance(sub, ast.stmt):
            yield sub
        elif isinstance(sub, _COMPOUND_WRAPPERS):
            yield from sub.body


def _render_py_func(node, keep: set[str], prefix: str, indent: str,
                    lines: list[str]) -> list[str]:
    q = f"{prefix}.{node.name}" if prefix else node.name
    if q in keep:
        return [_segment(lines, node)]
    if _has_kept_descendant(q, keep):
        out = _py_func_head(node, indent)
        out.extend(_render_py_func_body(node.body, keep, q,
                                        indent + "    ", lines))
        return out
    return _func_signature(node, indent)


def _render_py_func_body(body, keep: set[str], prefix: str, indent: str,
                         lines: list[str]) -> list[str]:
    """Children of a shell function. Compound statements (if/try/...)
    are recursed into: a conditionally-defined nested function is a
    symbol like any other and must render, not vanish."""
    out: list[str] = []
    for child in body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.extend(_render_py_func(child, keep, prefix, indent, lines))
        elif isinstance(child, ast.ClassDef):
            out.extend(_render_py_class(child, keep, prefix, indent, lines))
        else:
            for sub in _compound_stmts(child):
                out.extend(_render_py_func_body([sub], keep, prefix,
                                                indent, lines))
    return out


def _render_py_class(node, keep: set[str], prefix: str, indent: str,
                     lines: list[str]) -> list[str]:
    q = f"{prefix}.{node.name}" if prefix else node.name
    if q in keep:
        return [_segment(lines, node)]
    if _has_kept_descendant(q, keep):
        out = _py_class_head(node, indent)
        body = _render_py_class_body(node.body, keep, q,
                                     indent + "    ", lines)
        out.extend(body if body else [f"{indent}    ..."])
        return out
    return _class_signature(node, indent)


def _render_py_class_body(body, keep: set[str], prefix: str, indent: str,
                          lines: list[str]) -> list[str]:
    """Children of a shell class: methods and nested classes render
    recursively, class-level assignments mirror _class_signature
    (verbatim segment when the attribute itself is kept, unparsed
    line otherwise), and compound statements are recursed into so a
    method defined under `if TYPE_CHECKING:` still renders."""
    out: list[str] = []
    for child in body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.extend(_render_py_func(child, keep, prefix, indent, lines))
        elif isinstance(child, ast.ClassDef):
            out.extend(_render_py_class(child, keep, prefix, indent, lines))
        elif isinstance(child, (ast.Assign, ast.AnnAssign)):
            names: list[str] = []
            targets = child.targets if isinstance(child, ast.Assign) \
                else [child.target]
            for target in targets:
                names.extend(_target_names(target))
            if any(f"{prefix}.{n}" in keep for n in names):
                out.append(_segment(lines, child))
            else:
                try:
                    out.append(f"{indent}{ast.unparse(child)}")
                except Exception:
                    pass
        else:
            # The class docstring is in the head; other statements
            # are body and stay dropped, as in signatures mode —
            # except compounds, whose contained defs are symbols.
            for sub in _compound_stmts(child):
                out.extend(_render_py_class_body([sub], keep, prefix,
                                                 indent, lines))
    return out


def _render_py_module_stmt(node, keep: set[str], lines: list[str],
                           out: list[str]) -> None:
    """One module-level statement -> elements of the slice.

    Mirrors _slice_python's branch order; the tail recurses into
    compound statements (if/try/with/...) so conditionally-defined
    symbols render instead of vanishing (audit G13 F1)."""
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        out.append(ast.unparse(node))
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        out.extend(_render_py_func(node, keep, "", "", lines))
    elif isinstance(node, ast.ClassDef):
        out.extend(_render_py_class(node, keep, "", "", lines))
    elif _is_type_alias(node):
        try:
            out.append(ast.unparse(node))
        except Exception:
            pass
    elif isinstance(node, ast.Assign):
        names: list[str] = []
        for target in node.targets:
            names.extend(_target_names(target))
        if any(n in keep for n in names):
            out.append(_segment(lines, node))
        else:
            try:
                text = ast.unparse(node)
            except Exception:
                return
            if len(text) <= 200:
                out.append(text)
    elif isinstance(node, ast.Expr) \
            and isinstance(node.value, ast.Constant) \
            and isinstance(node.value.value, str) and not out:
        value = node.value.value.strip()
        out.append(f'"""{value.splitlines()[0]}"""' if value else '""""""')
    else:
        for sub in _compound_stmts(node):
            _render_py_module_stmt(sub, keep, lines, out)


def _slice_python_symbols(source: str, keep: set[str]) -> str:
    """Symbol slice of a parseable Python file.

    Mirrors _slice_python's conventions (and its "\\n\\n" join): the
    elements are imports, alias/constant lines, signature renderings,
    class renderings, and — for kept symbols — verbatim source
    segments.
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    out: list[str] = []
    for node in tree.body:
        _render_py_module_stmt(node, keep, lines, out)
    text = "\n\n".join(out).strip()
    return text + ("\n" if text else "")


# ---------------------------------------------------------------------------
# Generic lite rendering: line ranges + signature collapse
# ---------------------------------------------------------------------------

def _is_context_line(line: str, language: str) -> bool:
    """Always-context at top level: imports / package / preprocessor."""
    if language in ("typescript", "javascript"):
        return bool(_IMPORT_RE.match(line))
    if language in ("go", "rust", "java", "csharp"):
        return bool(_IMPORT_LINE_RES[language].match(line))
    if language in ("php", "kotlin", "swift"):
        return bool(_EXTRA_CFG[language]["import"].match(line))
    if language == "ruby":
        return bool(_RB_REQUIRE_RE.match(line))
    if language in ("c", "cpp"):
        return bool(_PREPROC_RE.match(line))
    if language == "scala":
        return bool(_SC_IMPORT_RE.match(line))
    if language == "python":  # fallback outline only
        return bool(re.match(r"^(import |from )", line))
    return False


def _is_interior_line(line: str, language: str) -> bool:
    """Always-context inside a container shell: field/attribute lines
    (the lite slicers' own heuristic — a `;`-terminated line with no
    call parens), C++ access labels, annotation lines, Ruby
    attr/const lines."""
    stripped = line.strip()
    if not stripped:
        return False
    if language == "ruby":
        return bool(_RB_ATTR_RE.match(line) or _RB_CONST_RE.match(line)
                    or _RB_REQUIRE_RE.match(line))
    if language in ("python", "scala"):
        return False
    if stripped.startswith("@") or stripped.startswith("#["):
        return True
    if _ACCESS_RE.match(line):
        return True
    return "(" not in stripped and stripped.endswith((";", ","))


def _closing_line(lines: list[str], sym: Symbol, language: str) -> str:
    """The container's closing line (`}`, `};`, `end`), or ""."""
    if sym.end <= sym.head_end or language == "python":
        return ""
    last = lines[sym.end].strip()
    if language == "ruby":
        if last == "end" or last.startswith(("end ", "end.", "end)")):
            return lines[sym.end]
        return ""
    if last.startswith("}"):
        return lines[sym.end]
    return ""


def _structure(symbols: list[Symbol]) -> dict:
    """Parent/children by span containment: {id(parent)|None: [child]}.

    Equal spans are siblings, never parent/child, and the iteration
    order is source order (start asc, wider span first)."""
    ordered = sorted(symbols, key=lambda s: (s.start, -s.end))
    children: dict = {}
    stack: list[Symbol] = []
    for sym in ordered:
        while stack and not (stack[-1].start <= sym.start
                             and sym.end <= stack[-1].end
                             and (stack[-1].start, stack[-1].end)
                             != (sym.start, sym.end)):
            stack.pop()
        parent = stack[-1] if stack else None
        children.setdefault(id(parent) if parent else None, []).append(sym)
        stack.append(sym)
    return children


def _sig_render(lines: list[str], sym: Symbol, language: str) -> str:
    """Signature rendering of one non-selected function/method."""
    pre = lines[sym.start:sym.decl]
    decl = sym.decl
    line = lines[decl]
    if language in ("typescript", "javascript"):
        if "=>" in line:
            sig = line.split("=>")[0].rstrip() + " => { /* ... */ };"
        elif "{" in line:
            sig = _sig_before_body(line) + " { /* ... */ }"
        else:
            sig = line.rstrip()
        return "\n".join(pre + [sig])
    if language in ("c", "cpp"):
        owner = sym.parent.split("::")[-1] if sym.parent else None
        head = _c_func_head(lines, decl, language, bare_name=owner)
        if head is not None:
            return "\n".join(pre + [_c_sig_text(lines, decl, head)])
        return "\n".join(lines[sym.start:sym.head_end + 1])
    if language == "scala":
        d = _scala_def(lines, decl, len(lines))
        if d is not None:
            return "\n".join(pre + [d[0]])
        return "\n".join(lines[sym.start:sym.end + 1])
    if language == "ruby":
        return "\n".join(lines[sym.start:decl + 1])
    if language == "python":  # fallback outline: the def line is the sig
        return line
    # go / rust / java / csharp / php / kotlin / swift
    if "{" in line:
        return "\n".join(pre + [_sig_before_body(line) + " { /* ... */ }"])
    if line.rstrip().endswith(";"):
        return "\n".join(lines[sym.start:sym.end + 1])  # bodyless decl
    return "\n".join(lines[sym.start:sym.head_end + 1])


def _render_symbol(lines: list[str], sym: Symbol, children: dict,
                   keep: set[str], language: str) -> str:
    kids = children.get(id(sym), [])
    if sym.qualified in keep or sym.kind in _VERBATIM_KINDS:
        return "\n".join(lines[sym.start:sym.end + 1])
    if kids or sym.kind in _CONTAINER_KINDS:
        parts = ["\n".join(lines[sym.start:sym.head_end + 1])]
        closing = _closing_line(lines, sym, language)
        interior_end = sym.end if closing else sym.end + 1
        pos = sym.head_end + 1
        for kid in kids:
            if kid.start < pos:
                continue
            ctx = [lines[t] for t in range(pos, kid.start)
                   if _is_interior_line(lines[t], language)]
            if ctx:
                parts.append("\n".join(ctx))
            parts.append(_render_symbol(lines, kid, children, keep,
                                         language))
            pos = kid.end + 1
        ctx = [lines[t] for t in range(pos, interior_end)
               if _is_interior_line(lines[t], language)]
        if ctx:
            parts.append("\n".join(ctx))
        if closing:
            parts.append(closing)
        return "\n".join(p for p in parts if p != "")
    return _sig_render(lines, sym, language)


def _render_lite(lines: list[str], symbols: list[Symbol],
                 keep: set[str], language: str) -> str:
    children = _structure(symbols)
    blocks: list[str] = []
    pos = 0
    for sym in children.get(None, []):
        if sym.start < pos:
            continue
        ctx = [lines[t] for t in range(pos, sym.start)
               if _is_context_line(lines[t], language)]
        if ctx:
            blocks.append("\n".join(ctx))
        blocks.append(_render_symbol(lines, sym, children, keep, language))
        pos = sym.end + 1
    ctx = [lines[t] for t in range(pos, len(lines))
           if _is_context_line(lines[t], language)]
    if ctx:
        blocks.append("\n".join(ctx))
    text = "\n\n".join(b for b in blocks if b.strip())
    text = text.strip()
    return text + ("\n" if text else "")


def slice_with_symbols(path: str, source: str, keep: set[str],
                       cache=None) -> str:
    """Slice `source` to the symbols named by `keep` (qualified names).

    Python uses the ast renderer; every other outlined language uses
    the generic line-range renderer over its outline spans. A
    language with no outline returns the source unchanged (callers
    only route outlined files here; this is a defensive default).

    `cache` (v0.20): optional cache.ProjectCache — the rendered text
    is a pure function of (path, source, keep set), so it is stored
    under exactly those dimensions (cache.py).
    """
    if cache is not None:
        hit = cache.get_symslice(path, source, keep)
        if hit is not None:
            return hit
    language = language_for(path)
    if language == "python":
        try:
            ast.parse(source)
        except Exception:
            symbols = _py_fallback_outline(source.splitlines())
            text = _render_lite(source.splitlines(), symbols, keep, language)
        else:
            text = _slice_python_symbols(source, keep)
    else:
        symbols = outline_source(source, language, path)
        if symbols is None:
            return source
        text = _render_lite(source.splitlines(), symbols, keep, language)
    if cache is not None:
        cache.put_symslice(path, source, keep, text)
    return text


# ---------------------------------------------------------------------------
# Selection resolution
# ---------------------------------------------------------------------------

class UnknownSymbolError(ValueError):
    """A spec entry matched no symbol anywhere it was allowed to look.

    Carries `unknown` (the entries) and `suggestions`
    ({entry: [near-miss names]}) so the CLI can exit 2 with a useful
    message instead of silently exporting less context.
    """

    def __init__(self, unknown: list[str],
                 suggestions: dict[str, list[str]]):
        self.unknown = unknown
        self.suggestions = suggestions
        parts = []
        for entry in unknown:
            hint = suggestions.get(entry) or []
            parts.append(f"{entry!r}" + (f" (did you mean: {', '.join(hint)})"
                                         if hint else ""))
        super().__init__("unknown symbol(s): " + "; ".join(parts))


def parse_symbol_specs(symbols) -> list[str]:
    """Normalise a --symbols value: a comma string or a list of
    (possibly comma-joined) strings -> ordered unique spec entries."""
    if symbols is None:
        return []
    raw = [symbols] if isinstance(symbols, str) else list(symbols)
    specs: list[str] = []
    for item in raw:
        for part in str(item).split(","):
            part = part.strip()
            if part and part not in specs:
                specs.append(part)
    return specs


_GLOB_CHARS = set("*?[")


def _name_matches(pattern: str, sym: Symbol) -> bool:
    """Match a spec pattern against one symbol.

    Exact: the full qualified name, the bare name, or any dotted
    suffix of the qualified name (`Store.total` matches
    `Shop.Store.total` and `ns::Store::total`) — qualification is
    context, and a pattern that names the tail of it is unambiguous
    about what it means; if the tail exists in several files, the
    ambiguity report says so. Globs fnmatch the qualified or bare
    name, or the qualified name with a leading segment wildcard.
    """
    if any(c in pattern for c in _GLOB_CHARS):
        return fnmatch.fnmatchcase(sym.qualified, pattern) \
            or fnmatch.fnmatchcase(sym.name, pattern) \
            or fnmatch.fnmatchcase(sym.qualified, "*." + pattern) \
            or fnmatch.fnmatchcase(sym.qualified, "*::" + pattern)
    return pattern == sym.qualified or pattern == sym.name \
        or sym.qualified.endswith("." + pattern) \
        or sym.qualified.endswith("::" + pattern)


def _split_file_scope(entry: str, paths: set[str]) -> tuple[str | None, str]:
    """Split `file.py:symbol` -> (file glob, symbol pattern).

    A colon only scopes when the part before it names (or globs) a
    scanned file; `Store::total` therefore stays a symbol pattern.
    """
    for i, ch in enumerate(entry):
        if ch != ":":
            continue
        if i > 0 and entry[i - 1] == ":":
            continue
        if i + 1 < len(entry) and entry[i + 1] == ":":
            continue
        prefix, rest = entry[:i], entry[i + 1:]
        if not rest:
            continue
        if prefix in paths or any(fnmatch.fnmatchcase(p, prefix)
                                  for p in paths):
            return prefix, rest
    return None, entry


def resolve_symbol_selection(scan_result, symbols, sources: dict[str, str],
                             cache=None):
    """Resolve spec entries against every scanned file's outline.

    `sources` maps path -> source text for the scan's files. Returns
    (symbol_map, report, outlines):
      symbol_map: {path: set(qualified names to keep with bodies)}
      report:     {"requested", "matches", "ambiguous", "files"}
                  for the manifest / CLI / MCP surfaces
      outlines:   {path: [Symbol]} for files that have one

    Raises UnknownSymbolError when any entry matches nothing.

    `cache` (v0.20): optional cache.ProjectCache for the per-file
    outlines — an outline is a pure function of (path, source), so
    hits rebuild the same Symbol rows from the stored dicts.
    """
    specs = parse_symbol_specs(symbols)
    if not specs:
        raise ValueError("empty symbol selection")
    paths = {e.path for e in scan_result.files}
    outlines: dict[str, list[Symbol]] = {}
    for entry in scan_result.files:
        source = sources.get(entry.path, "")
        syms = None
        if cache is not None:
            rows = cache.get_outline(entry.path, source)
            if rows is not None:
                try:
                    syms = [Symbol(**row) for row in rows]
                except TypeError:
                    syms = None  # shape drift: recompute below
        if syms is None:
            syms = outline_source(source, entry.language, entry.path)
            if cache is not None and syms is not None:
                from dataclasses import asdict
                cache.put_outline(entry.path, source,
                                   [asdict(s) for s in syms])
        if syms is not None:
            outlines[entry.path] = syms
    known: set[str] = set()
    for syms in outlines.values():
        for sym in syms:
            if sym.selectable:
                known.add(sym.qualified)
                known.add(sym.name)
    symbol_map: dict[str, set[str]] = {}
    matches: dict[str, list[dict]] = {}
    ambiguous: list[str] = []
    unknown: list[str] = []
    for entry in specs:
        scope, pattern = _split_file_scope(entry, paths)
        found: list[tuple[str, Symbol]] = []
        for path, syms in outlines.items():
            if scope is not None and not fnmatch.fnmatchcase(path, scope):
                continue
            for sym in syms:
                if sym.selectable and _name_matches(pattern, sym):
                    found.append((path, sym))
        if not found:
            unknown.append(entry)
            continue
        matches[entry] = [{"path": p, "symbol": s.qualified}
                          for p, s in found]
        if len({p for p, _s in found}) > 1:
            ambiguous.append(entry)
        for p, s in found:
            symbol_map.setdefault(p, set()).add(s.qualified)
    if unknown:
        suggestions = {
            entry: difflib.get_close_matches(
                _split_file_scope(entry, paths)[1], sorted(known),
                n=3, cutoff=0.5)
            for entry in unknown
        }
        raise UnknownSymbolError(unknown, suggestions)
    files_block: dict[str, list[str]] = {}
    for path, keep in symbol_map.items():
        seen: list[str] = []
        for sym in outlines.get(path, []):
            if sym.qualified in keep and sym.qualified not in seen:
                seen.append(sym.qualified)
        files_block[path] = seen
    report = {
        "requested": specs,
        "matches": matches,
        "ambiguous": ambiguous,
        "files": files_block,
    }
    return symbol_map, report, outlines
