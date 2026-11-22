"""GraphQL SDL outline: outline only, never a reduced schema.

Static, best-effort parsing (regex + brace matching over the type
system, not a full GraphQL grammar). Output is a labelled outline of
the types reachable by name from the selection, with their fields.
SDL parsing gaps degrade to missing entries the manifest can list,
which is exactly why SDL never gets the full treatment in v0.1.
"""
from __future__ import annotations

import re

from .loader import SchemaError
from .terms import score_against, task_terms

OUTLINE_LABEL = "GraphQL SDL outline - not a complete reduced schema"
BUILTIN_SCALARS = {"String", "Int", "Float", "Boolean", "ID"}

_DEF_START = re.compile(
    r"(?m)(?:^|\})[ \t]*(extend[ \t]+)?(type|interface|input|enum|union|scalar|schema|directive)[ \t]+"
)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FIELD_TYPE = re.compile(r"(?:\[|[A-Za-z_])[\[\]\w!]*")
_TYPE_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _strip_sdl(text: str) -> str:
    text = re.sub(r'"""(?:\\.|[^\\])*?"""', " ", text, flags=re.S)
    # Single-line strings cannot contain a raw newline in GraphQL, so
    # the pattern must not cross one either: a stray quote in a comment
    # would otherwise swallow every definition up to the next quote,
    # possibly lines later.
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', " ", text)
    text = re.sub(r"#[^\n]*", "", text)
    return text


def _brace_body(segment: str):
    """Return the body inside the first balanced {...} of a segment."""
    start = segment.find("{")
    if start < 0:
        return None
    depth = 0
    for idx in range(start, len(segment)):
        ch = segment[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return segment[start + 1:idx]
    return segment[start + 1:]


def _skip_ws(text, i):
    while i < len(text) and (text[i].isspace() or text[i] == ","):
        i += 1
    return i


def _skip_balanced(text, i, opener, closer):
    """Index just past the balanced closer for the opener at text[i]."""
    depth = 0
    while i < len(text):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _skip_directive(text, i):
    """Index just past a directive application starting at text[i] == '@',
    including its balanced (...) argument list when present."""
    m = _NAME.match(text, i + 1)
    j = m.end() if m else i + 1
    j = _skip_ws(text, j)
    if j < len(text) and text[j] == "(":
        j = _skip_balanced(text, j, "(", ")")
    return j


def _skip_default(text, i):
    """Index just past a default value starting after the '=' at text[i]:
    a balanced {...} or [...] span, or one scalar token."""
    j = _skip_ws(text, i + 1)
    if j < len(text):
        if text[j] == "{":
            return _skip_balanced(text, j, "{", "}")
        if text[j] == "[":
            return _skip_balanced(text, j, "[", "]")
        m = re.match(r"[^\s,]+", text[j:])
        if m:
            return j + m.end()
    return j


def _split_top_level(text):
    """Split on commas that sit at bracket depth zero."""
    parts = []
    depth = 0
    start = 0
    for idx, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:idx])
            start = idx + 1
    parts.append(text[start:])
    return parts


_ARG = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*((?:\[|[A-Za-z_])[\[\]\w!]*)"
)


def _parse_args(args_text):
    """One argument per top-level comma piece, anchored name: type.
    Default values (= ...) and trailing directives on a piece are not
    arguments and are ignored, so a name: type pair inside a default
    object is never mistaken for an argument."""
    args = []
    if not args_text:
        return args
    for piece in _split_top_level(args_text):
        m = _ARG.match(piece)
        if m:
            args.append({"name": m.group(1), "type": m.group(2)})
    return args


def _parse_fields(body):
    """Token-scan a definition body for fields. Bodies are scanned as a
    stream, not line by line, so several fields declared on one line
    (a common compact SDL style) are all found; after each field's
    type, directive applications and a default value (input fields)
    are skipped before scanning resumes, so neither can masquerade
    as the next field."""
    fields = []
    if not body:
        return fields
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch.isspace() or ch == ",":
            i += 1
            continue
        if ch == "@":
            i = _skip_directive(body, i)
            continue
        m = _NAME.match(body, i)
        if not m:
            i += 1
            continue
        name = m.group(0)
        j = _skip_ws(body, m.end())
        args_text = None
        if j < n and body[j] == "(":
            k = _skip_balanced(body, j, "(", ")")
            args_text = body[j + 1:k - 1] if k > j + 1 else ""
            j = _skip_ws(body, k)
        if j >= n or body[j] != ":":
            i = m.end()
            continue
        tm = _FIELD_TYPE.match(body, _skip_ws(body, j + 1))
        if not tm:
            i = m.end()
            continue
        j = tm.end()
        while True:
            k = _skip_ws(body, j)
            if k < n and body[k] == "@":
                j = _skip_directive(body, k)
            elif k < n and body[k] == "=":
                j = _skip_default(body, k)
            else:
                j = k
                break
        fields.append({
            "name": name,
            "type": tm.group(0),
            "args": _parse_args(args_text),
        })
        i = j
    return fields


def _parse_values(body):
    """All value names in a body (enum values, union members written
    in a body): directive applications are stripped first, so several
    values on one line are all found and a directive's arguments are
    never mistaken for values."""
    values = []
    if not body:
        return values
    out = []
    i, n = 0, len(body)
    while i < n:
        if body[i] == "@":
            i = _skip_directive(body, i)
        else:
            out.append(body[i])
            i += 1
    return _NAME.findall("".join(out))


def parse_sdl(text: str):
    """Returns (types, directive_names). types maps name -> def dict,
    in source order; extend blocks merge into the base def."""
    clean = _strip_sdl(text)
    starts = [m for m in _DEF_START.finditer(clean)]
    types = {}
    order = []
    directives = []
    for idx, m in enumerate(starts):
        end = starts[idx + 1].start() if idx + 1 < len(starts) else len(clean)
        segment = clean[m.start():end]
        kind = m.group(2)
        rest = segment[m.end() - m.start():]
        if kind == "directive":
            nm = _NAME.search(rest)
            if nm:
                directives.append(nm.group(0))
            continue
        header = rest.split("{", 1)[0]
        if kind == "schema":
            name = "schema"
        else:
            nm = _NAME.search(rest)
            if not nm:
                continue
            name = nm.group(0)
        body = _brace_body(segment)
        entry = {
            "name": name,
            "kind": kind,
            "fields": [],
            "values": [],
            "members": [],
            "interfaces": [],
        }
        if kind in ("type", "interface", "input"):
            entry["fields"] = _parse_fields(body)
            impl = re.search(r"\bimplements\b([^@{]*)", header)
            if impl:
                entry["interfaces"] = _NAME.findall(impl.group(1))
        elif kind == "enum":
            entry["values"] = _parse_values(body)
        elif kind == "union":
            eq = header.find("=")
            if eq >= 0:
                entry["members"] = _NAME.findall(header[eq + 1:])
            elif body:
                entry["members"] = _parse_values(body)
        elif kind == "schema":
            entry["fields"] = _parse_fields(body)
        if name in types:
            prior = types[name]
            prior["fields"].extend(
                f for f in entry["fields"]
                if f["name"] not in {p["name"] for p in prior["fields"]})
            prior["values"].extend(v for v in entry["values"] if v not in prior["values"])
            prior["members"].extend(v for v in entry["members"] if v not in prior["members"])
            prior["interfaces"].extend(
                v for v in entry["interfaces"] if v not in prior["interfaces"])
        else:
            types[name] = entry
            order.append(name)
    return [types[n] for n in order], directives


def _follow_names(entry):
    names = set()
    for field in entry["fields"]:
        names.update(_TYPE_TOKEN.findall(field["type"]))
        for arg in field["args"]:
            names.update(_TYPE_TOKEN.findall(arg["type"]))
    names.update(entry["interfaces"])
    names.update(entry["members"])
    return {n for n in names if n not in BUILTIN_SCALARS}


def outline_sdl(text, task=None, select_ids=None, keep_all=False):
    """Build the labelled outline for a GraphQL SDL document.

    Selection is ``keep_all``, else ``select_ids`` (exact type names
    only), else ``task`` wording. Reachability follows type names
    through field and argument types, implemented interfaces, and
    union members. Returns a result dict whose ``outline`` is the
    outline document, plus kept and dropped type names, warnings,
    and the selection echo. Never returns a reduced schema. Raises
    SchemaError when no types parse, an id is unknown, or the
    selection matches nothing.
    """
    types, directives = parse_sdl(text)
    by_name = {t["name"]: t for t in types}
    if not types:
        raise SchemaError(
            "no GraphQL type definitions could be parsed from the SDL; "
            "outline cannot be built"
        )
    selected = set()
    mode = "all" if keep_all else ("select" if select_ids else "task")
    if keep_all:
        selected = set(by_name)
    elif select_ids:
        unknown = [s for s in (x.strip() for x in select_ids)
                   if s and s not in by_name]
        if unknown:
            raise SchemaError(
                "unknown --select type name(s): " + ", ".join(sorted(unknown))
                + ". SDL selection is by exact type name."
            )
        selected = {x.strip() for x in select_ids if x.strip()}
    elif task:
        terms = task_terms(task)
        if not terms:
            raise SchemaError("--task produced no usable terms; use --select or --all")
        for entry in types:
            stacks = [
                (3, entry["name"]),
                (2, " ".join(f["name"] for f in entry["fields"])),
                (2, " ".join(entry["values"])),
            ]
            if score_against(terms, stacks) > 0:
                selected.add(entry["name"])
    else:
        raise SchemaError("nothing to select: pass --task, --select, or --all")
    if not selected:
        raise SchemaError(
            "selection matched no SDL types"
            + (f" for task {task!r}" if task else "")
            + "; try different terms or --select"
        )
    kept = set(selected)
    queue = list(selected)
    while queue:
        name = queue.pop()
        entry = by_name.get(name)
        if entry is None:
            continue
        for nxt in _follow_names(entry):
            if nxt in by_name and nxt not in kept:
                kept.add(nxt)
                queue.append(nxt)
    schema_entry = by_name.get("schema")
    if schema_entry is not None:
        # Root operation types may be wrapped (Query!, [Query]): compare
        # by bare type name, not by the raw type string.
        roots = set()
        for f in schema_entry["fields"]:
            roots.update(_TYPE_TOKEN.findall(f["type"]))
        if roots & kept:
            kept.add("schema")
    kept_types = [by_name[n] for n in (t["name"] for t in types) if n in kept]
    dropped_names = sorted(set(by_name) - kept)
    warnings = [
        "SDL treatment is outline only: reachability is by type name "
        "and this outline is not a complete reduced schema."
    ]
    if directives:
        warnings.append(
            "directive definitions are not outlined: "
            + ", ".join(sorted(set(directives)))
        )
    outline = {
        "treatment": "outline",
        "label": OUTLINE_LABEL,
        "format": "graphql-sdl",
        "types": kept_types,
        "dropped_types": dropped_names,
    }
    result = {
        "outline": outline,
        "kept": {"types": [t["name"] for t in kept_types]},
        "dropped": {"types": dropped_names},
        "unresolved": [],
        "warnings": warnings,
        "selection": {"mode": mode, "task": task, "select": select_ids or []},
    }
    return result


def render_outline_md(outline, source_name):
    """Render an outline dict as the human-readable ``OUTLINE.md``."""
    lines = [
        f"# GhostSchema outline: {source_name}",
        "",
        f"**{OUTLINE_LABEL}.** This file lists the types reachable for "
        "the task, with their fields. It is a reading aid, not a "
        "complete or valid standalone schema document.",
        "",
    ]
    for entry in outline["types"]:
        lines.append(f"## {entry['name']} ({entry['kind']})")
        if entry["interfaces"]:
            lines.append(f"Implements: {', '.join(entry['interfaces'])}")
        if entry["members"]:
            lines.append(f"Members: {', '.join(entry['members'])}")
        for value in entry["values"]:
            lines.append(f"- {value}")
        for field in entry["fields"]:
            args = ""
            if field["args"]:
                args = " (" + ", ".join(
                    f"{a['name']}: {a['type']}" for a in field["args"]) + ")"
            lines.append(f"- {field['name']}{args}: {field['type']}")
        lines.append("")
    if outline["dropped_types"]:
        lines.append("## Dropped types (not reachable for this selection)")
        for name in outline["dropped_types"]:
            lines.append(f"- {name}")
        lines.append("")
    return "\n".join(lines)
