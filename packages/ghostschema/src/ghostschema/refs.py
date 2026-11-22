"""Local $ref graph helpers.

A $ref is local only when it is exactly "#" or starts with "#/".
Everything else (https URLs, file paths, bare fragments into other
documents) is external: GhostSchema never fetches it. External refs
are recorded as unresolved and left in place in reduced output.
"""
from __future__ import annotations

MISSING = object()


def is_local_ref(ref) -> bool:
    """True only for ``"#"`` or a ``"#/..."`` pointer into the same document."""
    return isinstance(ref, str) and (ref == "#" or ref.startswith("#/"))


def is_external_ref(ref) -> bool:
    """True for any other string $ref: a URL, a file path, or a fragment
    into another document. External refs are never fetched."""
    return isinstance(ref, str) and not is_local_ref(ref)


def pointer_parts(ref: str):
    """'#/components/schemas/Pet' -> ['components', 'schemas', 'Pet']."""
    if ref == "#":
        return []
    body = ref[2:] if ref.startswith("#/") else ref.lstrip("#")
    if not body:
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in body.split("/")]


def escape_part(part: str) -> str:
    """Escape one JSON Pointer segment (``~`` then ``/``)."""
    return part.replace("~", "~0").replace("/", "~1")


def make_pointer(parts) -> str:
    """Build a local ref from pointer segments: ``[]`` -> ``"#"``,
    ``['components', 'schemas', 'Pet']`` -> ``'#/components/schemas/Pet'``."""
    if not parts:
        return "#"
    return "#/" + "/".join(escape_part(str(p)) for p in parts)


def resolve(doc, ref: str):
    """Resolve a local ref against doc. Returns the node or MISSING."""
    node = doc
    for part in pointer_parts(ref):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isascii() and part.isdigit() \
                and len(part) <= 18 and int(part) < len(node):
            node = node[int(part)]
        else:
            return MISSING
    return node


def iter_refs(node, base_parts=()):
    """Yield (parts, ref) for every $ref at or below node.

    parts is the JSON-pointer path (as a list) of the object that
    carries the $ref, rooted at base_parts.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield list(base_parts), ref
        for key, value in node.items():
            yield from iter_refs(value, list(base_parts) + [key])
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            yield from iter_refs(value, list(base_parts) + [str(idx)])


_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head",
                 "patch", "trace"}
# Where a bare discriminator mapping name may live, in lookup order.
_NAME_SECTIONS = (("components", "schemas"), ("$defs",), ("definitions",))


def iter_implicit_refs(node, base_parts=()):
    """Yield (parts, via, value) for references that are not $ref keys.

    OpenAPI names other documents and operations without a $ref:

    - ``discriminator.mapping`` values name the subtype schemas a
      polymorphic schema can actually be (a local pointer, an external
      URI, or a bare schema name shorthand).
    - Link Objects carry ``operationId`` (an operation elsewhere in
      the same document) or ``operationRef`` (a pointer or external
      URI) instead of a $ref.

    A reduced spec that keeps the carrier but drops the target has a
    dangling reference the $ref closure check cannot see, so these are
    part of the reference graph too. A node counts as a Link Object
    when its parent key is ``links`` (responses and components alike).
    """
    if isinstance(node, dict):
        if len(base_parts) >= 2 and base_parts[-2] == "links":
            for key, via in (("operationId", "link.operationId"),
                             ("operationRef", "link.operationRef")):
                value = node.get(key)
                if isinstance(value, str) and value:
                    yield list(base_parts), via, value
        disc = node.get("discriminator")
        if isinstance(disc, dict):
            mapping = disc.get("mapping")
            if isinstance(mapping, dict):
                for key, value in mapping.items():
                    if isinstance(value, str) and value:
                        yield (list(base_parts) + ["discriminator",
                                                   "mapping", str(key)],
                               "discriminator.mapping", value)
        for key, value in node.items():
            yield from iter_implicit_refs(value, list(base_parts) + [key])
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            yield from iter_implicit_refs(value, list(base_parts) + [str(idx)])


def find_operation(doc, operation_id):
    """Pointer parts of the operation with this operationId in doc's
    paths/webhooks, or None when the document has no such operation."""
    if not isinstance(doc, dict):
        return None
    for kind in ("paths", "webhooks"):
        section = doc.get(kind)
        if not isinstance(section, dict):
            continue
        for path, item in section.items():
            if not isinstance(item, dict):
                continue
            for method, node in item.items():
                if method.lower() in _HTTP_METHODS and isinstance(node, dict) \
                        and node.get("operationId") == operation_id:
                    return [kind, path, method]
    return None


def _name_candidate(doc, name):
    """Pointer parts for a bare schema name, or None if no known
    section of doc holds it."""
    for section in _NAME_SECTIONS:
        node = doc
        for part in section:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict) and name in node:
            return list(section) + [name]
    return None


def closure(doc, seeds):
    """Follow local $refs transitively from seed nodes.

    seeds: list of (parts, node) for subtrees of doc to start from.
    Returns (keep_pointers, unresolved) where keep_pointers is a set of
    canonical local pointer strings that were reached (including the
    seed subtrees' own pointers, which the caller supplies), and
    unresolved is a list of {"ref": ..., "from": pointer} for external
    refs encountered. Local refs that do not resolve in doc are also
    recorded in unresolved with a "missing_local" flag: they are broken
    in the source, and the reduced output cannot fix them.

    Implicit references (see iter_implicit_refs: discriminator
    mappings and Link Object operationId/operationRef) are followed the
    same way, transitively; their unresolved entries carry a "via"
    naming the construct that referenced them. External implicit
    targets are never fetched either.
    """
    keep = set()
    unresolved = []
    seen_unresolved = set()
    queue = [(list(parts), node) for parts, node in seeds]
    scanned = set()

    def record(ref, from_parts, via=None, missing=False):
        key = (ref, make_pointer(from_parts), via)
        if key in seen_unresolved:
            return
        seen_unresolved.add(key)
        entry = {"ref": ref, "from": make_pointer(from_parts)}
        if missing:
            entry["missing_local"] = True
        if via:
            entry["via"] = via
        unresolved.append(entry)

    def follow_pointer(target_parts, ref, from_parts, via=None):
        canon = make_pointer(target_parts)
        if canon in keep:
            return
        keep.add(canon)
        target = resolve(doc, canon)
        if target is MISSING:
            record(ref, from_parts, via=via, missing=True)
        else:
            queue.append((list(target_parts), target))

    def follow_ref(ref, from_parts, via=None):
        if is_local_ref(ref):
            follow_pointer(pointer_parts(ref), ref, from_parts, via=via)
        else:
            # External: never fetched, left in place, listed unresolved.
            record(ref, from_parts, via=via)

    while queue:
        parts, node = queue.pop()
        marker = make_pointer(parts)
        if marker in scanned:
            continue
        scanned.add(marker)
        for ref_parts, ref in iter_refs(node, parts):
            follow_ref(ref, ref_parts)
        for ref_parts, via, value in iter_implicit_refs(node, parts):
            if via == "link.operationId":
                found = find_operation(doc, value)
                if found is None:
                    record(value, ref_parts, via=via, missing=True)
                else:
                    follow_pointer(found, value, ref_parts, via=via)
            elif via == "discriminator.mapping" and not is_local_ref(value) \
                    and not any(c in value for c in "/#:."):
                # Bare schema-name shorthand: follow it when a known
                # section holds it, else it is broken in the source.
                candidate = _name_candidate(doc, value)
                if candidate is None:
                    record(value, ref_parts, via=via, missing=True)
                else:
                    follow_pointer(candidate, value, ref_parts, via=via)
            else:
                follow_ref(value, ref_parts, via=via)
    return keep, unresolved


def check_closure(doc):
    """Every local $ref in doc must resolve inside doc.

    Returns a list of failure strings (empty means closed). External
    refs are ignored here: they are unresolved by design, not broken.
    """
    failures = []
    for parts, ref in iter_refs(doc):
        if is_local_ref(ref) and resolve(doc, ref) is MISSING:
            failures.append(f"{make_pointer(parts)} -> {ref} does not resolve")
    return failures
