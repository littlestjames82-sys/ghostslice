"""Full-treatment slicing for JSON specs: OpenAPI 3.x and standalone
JSON Schema. Selection (task terms or explicit ids) plus transitive
local $ref reachability. Remote $refs are never fetched; they are
left in place and recorded as unresolved. The reduced document is
self-checked for $ref closure before it is allowed out.
"""
from __future__ import annotations

import copy

from .loader import SchemaError
from .refs import check_closure, closure, iter_refs, make_pointer, pointer_parts, resolve, MISSING
from .terms import score_against, task_terms

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
DEF_SECTIONS = ("$defs", "definitions")


# ---------------------------------------------------------------- OpenAPI

def list_operations(doc):
    """List every operation in an OpenAPI document's ``paths`` and
    ``webhooks``. Each entry carries its section kind, path, method,
    node, operationId (or a ``METHOD /path`` fallback), and a display
    label such as ``GET /pets/{petId} (getPet)``."""
    ops = []
    for kind in ("paths", "webhooks"):
        section = doc.get(kind)
        if not isinstance(section, dict):
            continue
        for path, item in section.items():
            if not isinstance(item, dict):
                continue
            for method, node in item.items():
                if method.lower() in HTTP_METHODS and isinstance(node, dict):
                    op_id = node.get("operationId") or f"{method.upper()} {path}"
                    ops.append({
                        "kind": kind, "path": path, "method": method.lower(),
                        "node": node, "op_id": op_id,
                        "label": f"{method.upper()} {path} ({op_id})"
                        if node.get("operationId") else f"{method.upper()} {path}",
                    })
    return ops


def component_entries(doc):
    """Return ``{section: {name: node}}`` for an OpenAPI document's
    ``components``, keeping only sections whose value is an object."""
    comps = doc.get("components")
    out = {}
    if isinstance(comps, dict):
        for section, entries in comps.items():
            if isinstance(entries, dict):
                out[section] = entries
    return out


def _op_haystacks(doc, op):
    item = doc.get(op["kind"], {}).get(op["path"], {})
    params = []
    for holder in (item, op["node"]):
        if isinstance(holder, dict):
            for param in holder.get("parameters", []) or []:
                if isinstance(param, dict) and param.get("name"):
                    params.append(str(param["name"]))
    ref_names = []
    for _parts, ref in iter_refs(op["node"]):
        if ref.startswith("#/"):
            parts = pointer_parts(ref)
            if parts:  # "#/" has no segments; there is no name to add
                ref_names.append(parts[-1])
    return [
        (3, op["op_id"]),
        (3, op["path"]),
        (2, op["node"].get("summary", "")),
        (1, op["node"].get("description", "")),
        (2, " ".join(op["node"].get("tags", []) or [])),
        (2, " ".join(params)),
        (2, " ".join(ref_names)),
    ]


def _entry_haystacks(section, name, node):
    stacks = [(3 if section == "schemas" else 2, name)]
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            stacks.append((2, " ".join(props.keys())))
        stacks.append((2, str(node.get("title", ""))))
        stacks.append((1, str(node.get("description", ""))))
    return stacks


def _resolve_select_openapi(doc, ops, comps, select_ids):
    """Returns (op_keys, seed_parts, unknown)."""
    op_keys = set()
    seed_parts = []
    unknown = []
    by_opid = {}
    for op in ops:
        by_opid.setdefault(op["op_id"], op)
        if op["node"].get("operationId"):
            by_opid.setdefault(op["node"]["operationId"], op)
    for raw in select_ids:
        sid = raw.strip()
        if not sid:
            continue
        if sid.startswith("#/"):
            parts = pointer_parts(sid)
            if resolve(doc, sid) is MISSING:
                unknown.append(sid)
                continue
            seed_parts.append(parts)
            if len(parts) == 3 and parts[0] in ("paths", "webhooks") \
                    and parts[2].lower() in HTTP_METHODS:
                op_keys.add((parts[0], parts[1], parts[2].lower()))
            continue
        if " " in sid:
            method, _, path = sid.partition(" ")
            hit = [op for op in ops if op["path"] == path.strip()
                   and op["method"] == method.strip().lower()]
            if hit:
                for op in hit:
                    op_keys.add((op["kind"], op["path"], op["method"]))
                continue
        if sid in by_opid:
            op = by_opid[sid]
            op_keys.add((op["kind"], op["path"], op["method"]))
            continue
        if sid.startswith("/"):
            hit = [op for op in ops if op["path"] == sid]
            if hit:
                for op in hit:
                    op_keys.add((op["kind"], op["path"], op["method"]))
                continue
            unknown.append(sid)
            continue
        matched = False
        for section, entries in comps.items():
            if sid in entries:
                seed_parts.append(["components", section, sid])
                matched = True
        if not matched:
            unknown.append(sid)
    return op_keys, seed_parts, unknown


def slice_openapi(doc, task=None, select_ids=None, keep_all=False):
    """Reduce an OpenAPI 3.x document to the selected operations and
    everything reachable from them by local $refs.

    Selection is ``keep_all``, else ``select_ids``, else ``task``
    wording. Returns a result dict with the reduced document, kept
    and dropped lists, unresolved (remote or broken) refs, warnings,
    and the selection echo. Raises SchemaError for an unknown select
    id, an empty task, no selection, or a selection matching nothing.
    The reduced document is closure-checked before it is returned.
    """
    ops = list_operations(doc)
    comps = component_entries(doc)
    op_keys = set()
    seed_parts = []
    mode = "all" if keep_all else ("select" if select_ids else "task")
    if keep_all:
        op_keys = {(op["kind"], op["path"], op["method"]) for op in ops}
        for section, entries in comps.items():
            for name in entries:
                seed_parts.append(["components", section, name])
    elif select_ids:
        op_keys, seed_parts, unknown = _resolve_select_openapi(doc, ops, comps, select_ids)
        if unknown:
            raise SchemaError(
                "unknown --select id(s): " + ", ".join(sorted(unknown))
                + ". Use operationIds, 'METHOD /path', schema names, or #/ pointers."
            )
    elif task:
        terms = task_terms(task)
        if not terms:
            raise SchemaError("--task produced no usable terms; use --select or --all")
        for op in ops:
            if score_against(terms, _op_haystacks(doc, op)) > 0:
                op_keys.add((op["kind"], op["path"], op["method"]))
        for section, entries in comps.items():
            for name, node in entries.items():
                if score_against(terms, _entry_haystacks(section, name, node)) > 0:
                    seed_parts.append(["components", section, name])
    else:
        raise SchemaError("nothing to select: pass --task, --select, or --all")
    seeded_items = set()
    for op in ops:
        if (op["kind"], op["path"], op["method"]) not in op_keys:
            continue
        seed_parts.append([op["kind"], op["path"], op["method"]])
        # Path-item level subtrees (parameters, servers, ...) apply to
        # every operation on the path and are copied into the output
        # with any kept operation, so their $refs must be followed too.
        item_key = (op["kind"], op["path"])
        if item_key not in seeded_items:
            seeded_items.add(item_key)
            item = doc.get(op["kind"], {}).get(op["path"], {})
            if isinstance(item, dict):
                for sub_key in item:
                    if sub_key.lower() not in HTTP_METHODS:
                        seed_parts.append([op["kind"], op["path"], sub_key])
    if not seed_parts:
        raise SchemaError(
            "selection matched no operations or schemas"
            + (f" for task {task!r}" if task else "")
            + "; try different terms or --select"
        )
    seeds = []
    for parts in seed_parts:
        node = resolve(doc, make_pointer(parts))
        if node is not MISSING:
            seeds.append((parts, node))
    keep_pointers, unresolved = closure(doc, seeds)
    seed_pointers = {make_pointer(p) for p in seed_parts}
    reduced = _reduce_openapi(doc, op_keys, keep_pointers, seed_pointers)
    kept_ops = {(op["kind"], op["path"], op["method"]) for op in list_operations(reduced)}
    kept = {
        "operations": sorted(op["label"] for op in ops
                             if (op["kind"], op["path"], op["method"]) in kept_ops),
        "schemas": sorted(reduced.get("components", {}).get("schemas", {}).keys()),
        "components": sorted(
            f"{section}/{name}"
            for section, entries in reduced.get("components", {}).items()
            if section != "schemas" and isinstance(entries, dict)
            for name in entries
        ),
    }
    dropped = {
        "operations": sorted(op["label"] for op in ops
                             if (op["kind"], op["path"], op["method"]) not in kept_ops),
        "schemas": sorted(set(comps.get("schemas", {})) - set(kept["schemas"])),
        "components": sorted(
            {f"{s}/{n}" for s, e in comps.items() if s != "schemas" for n in e}
            - set(kept["components"])
        ),
    }
    result = {
        "reduced_doc": reduced,
        "kept": kept,
        "dropped": dropped,
        "unresolved": unresolved,
        "warnings": [],
        "selection": {"mode": mode, "task": task, "select": select_ids or []},
    }
    _verify_closure(doc, reduced, unresolved, result)
    return result


def _reduce_openapi(doc, op_keys, keep_pointers, seed_pointers):
    keep_prefixes = set()
    for ptr in list(keep_pointers) + list(seed_pointers):
        parts = pointer_parts(ptr)
        for i in range(1, len(parts) + 1):
            keep_prefixes.add(tuple(parts[:i]))
    # A path item is kept whole only when the item pointer itself is a
    # ref target or a seed. A deeper pointer (a path-level parameters
    # entry, one operation) must not drag in sibling operations.
    whole_pointers = {
        ptr for ptr in list(keep_pointers) + list(seed_pointers)
        if len(pointer_parts(ptr)) == 2
    }

    def entry_kept(section, name):
        return ("components", section, name) in keep_prefixes

    out = {"openapi": doc.get("openapi")}
    for key in ("info", "servers", "externalDocs"):
        if key in doc:
            out[key] = copy.deepcopy(doc[key])
    kept_security_names = set()
    for kind in ("paths", "webhooks"):
        section = doc.get(kind)
        if not isinstance(section, dict):
            continue
        kept_items = {}
        for path, item in section.items():
            if not isinstance(item, dict):
                continue
            whole = make_pointer([kind, path]) in whole_pointers
            kept_ops_here = {}
            for method, node in item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(node, dict):
                    continue
                if whole or (kind, path, method.lower()) in op_keys \
                        or (kind, path, method.lower()) in keep_prefixes:
                    kept_ops_here[method] = copy.deepcopy(node)
                    for req in node.get("security", []) or []:
                        if isinstance(req, dict):
                            kept_security_names.update(req.keys())
            if kept_ops_here:
                new_item = {}
                for key, value in item.items():
                    if key.lower() not in HTTP_METHODS:
                        new_item[key] = copy.deepcopy(value)
                new_item.update(kept_ops_here)
                kept_items[path] = new_item
        if kept_items:
            out[kind] = kept_items
    comps = doc.get("components")
    if isinstance(comps, dict):
        new_comps = {}
        for section, entries in comps.items():
            if not isinstance(entries, dict):
                continue
            kept_entries = {name: copy.deepcopy(node)
                            for name, node in entries.items()
                            if entry_kept(section, name)}
            if kept_entries:
                new_comps[section] = kept_entries
        # securitySchemes named by kept operations must survive even
        # when nothing $refs them.
        schemes = comps.get("securitySchemes")
        if isinstance(schemes, dict) and kept_security_names:
            target = new_comps.setdefault("securitySchemes", {})
            for name in kept_security_names:
                if name in schemes and name not in target:
                    target[name] = copy.deepcopy(schemes[name])
        if new_comps:
            out["components"] = new_comps
    if isinstance(doc.get("security"), list):
        names = set()
        for req in doc["security"]:
            if isinstance(req, dict):
                names.update(req.keys())
        have = out.get("components", {}).get("securitySchemes", {})
        if names and all(n in have for n in names):
            out["security"] = copy.deepcopy(doc["security"])
    if isinstance(doc.get("tags"), list):
        used = set()
        for kind in ("paths", "webhooks"):
            for item in out.get(kind, {}).values():
                for method, node in item.items():
                    if method.lower() in HTTP_METHODS and isinstance(node, dict):
                        used.update(node.get("tags", []) or [])
        filtered = [t for t in doc["tags"]
                    if isinstance(t, dict) and t.get("name") in used]
        if filtered:
            out["tags"] = copy.deepcopy(filtered)
    return out


# ------------------------------------------------------------ JSON Schema

def slice_jsonschema(doc, task=None, select_ids=None, keep_all=False):
    """Reduce a standalone JSON Schema to the selected definitions
    and everything reachable from them by local $refs.

    ``select_ids`` may name definitions, use ``#/$defs/<name>``
    pointers, or select the root with ``root`` (also ``#`` /
    ``$root``). When the root is not selected and exactly one
    selected definition is kept, the reduced root is a ``$ref`` to
    it; with several kept, it is an ``anyOf`` of ``$ref`` entries.
    Returns the
    same result shape as :func:`slice_openapi` and raises
    SchemaError on the same failure classes.
    """
    defs = {}
    for section in DEF_SECTIONS:
        entries = doc.get(section)
        if isinstance(entries, dict):
            defs[section] = entries
    root_node = {k: v for k, v in doc.items() if k not in DEF_SECTIONS}
    has_defs = bool(defs)
    root_selected = False
    selected_defs = set()
    seed_parts = []
    mode = "all" if keep_all else ("select" if select_ids else "task")
    if keep_all:
        root_selected = True
        for section, entries in defs.items():
            for name in entries:
                selected_defs.add((section, name))
    elif select_ids:
        unknown = []
        for raw in select_ids:
            sid = raw.strip()
            if not sid:
                continue
            if sid in ("root", "#", "$root"):
                root_selected = True
                continue
            if sid.startswith("#/"):
                parts = pointer_parts(sid)
                if resolve(doc, sid) is MISSING:
                    unknown.append(sid)
                    continue
                seed_parts.append(parts)
                if len(parts) == 2 and parts[0] in DEF_SECTIONS:
                    selected_defs.add((parts[0], parts[1]))
                else:
                    root_selected = True
                continue
            matched = False
            for section, entries in defs.items():
                if sid in entries:
                    selected_defs.add((section, sid))
                    matched = True
            if not matched:
                unknown.append(sid)
        if unknown:
            raise SchemaError(
                "unknown --select id(s): " + ", ".join(sorted(unknown))
                + ". Use def names, #/$defs/<name> pointers, or 'root'."
            )
    elif task:
        terms = task_terms(task)
        if not terms:
            raise SchemaError("--task produced no usable terms; use --select or --all")
        root_stacks = [
            (2, str(doc.get("title", ""))),
            (1, str(doc.get("description", ""))),
            (2, " ".join((doc.get("properties") or {}).keys())
             if isinstance(doc.get("properties"), dict) else ""),
            (2, str(doc.get("$id", ""))),
        ]
        if score_against(terms, root_stacks) > 0:
            root_selected = True
        for section, entries in defs.items():
            for name, node in entries.items():
                if score_against(terms, _entry_haystacks("schemas", name, node)) > 0:
                    selected_defs.add((section, name))
    else:
        raise SchemaError("nothing to select: pass --task, --select, or --all")
    if not has_defs and not root_selected and not seed_parts:
        raise SchemaError(
            "this schema has no $defs/definitions to slice and the root "
            "was not selected; select 'root' or use --all"
        )
    if not root_selected and not selected_defs and not seed_parts:
        raise SchemaError(
            "selection matched nothing"
            + (f" for task {task!r}" if task else "")
            + "; try different terms or --select"
        )
    seeds = []
    if root_selected:
        seeds.append(([], root_node))
        seed_parts.append([])
    for section, name in sorted(selected_defs):
        seed_parts.append([section, name])
        seeds.append(([section, name], defs[section][name]))
    for parts in list(seed_parts):
        if parts and (len(parts) != 2 or parts[0] not in DEF_SECTIONS):
            node = resolve(doc, make_pointer(parts))
            if node is not MISSING:
                seeds.append((parts, node))
    keep_pointers, unresolved = closure(doc, seeds)
    seed_pointers = {make_pointer(p) for p in seed_parts if p}
    keep_prefixes = set()
    for ptr in list(keep_pointers) + list(seed_pointers):
        parts = pointer_parts(ptr)
        for i in range(1, len(parts) + 1):
            keep_prefixes.add(tuple(parts[:i]))
    if root_selected:
        reduced = copy.deepcopy(root_node)
    else:
        reduced = {k: copy.deepcopy(doc[k])
                   for k in ("$schema", "$id", "title", "description") if k in doc}
    present_defs = []
    for section, entries in defs.items():
        kept_entries = {name: copy.deepcopy(node)
                        for name, node in entries.items()
                        if (section, name) in keep_prefixes}
        if kept_entries:
            reduced[section] = kept_entries
            present_defs.extend((section, name) for name in kept_entries)
    if not root_selected:
        chosen = [(s, n) for (s, n) in present_defs if (s, n) in selected_defs]
        if len(chosen) == 1:
            reduced["$ref"] = make_pointer(list(chosen[0]))
        elif len(chosen) > 1:
            reduced["anyOf"] = [{"$ref": make_pointer([s, n])} for s, n in sorted(chosen)]
    all_def_names = sorted(f"{s}/{n}" for s, e in defs.items() for n in e)
    kept_def_names = sorted(f"{s}/{n}" for s, n in present_defs)
    result = {
        "reduced_doc": reduced,
        "kept": {"root": root_selected, "defs": kept_def_names},
        "dropped": {"defs": sorted(set(all_def_names) - set(kept_def_names))},
        "unresolved": unresolved,
        "warnings": [],
        "selection": {"mode": mode, "task": task, "select": select_ids or []},
    }
    _verify_closure(doc, reduced, unresolved, result)
    return result


def _verify_closure(original, reduced, unresolved, result):
    """Refs that resolved in the source must resolve in the output.
    Refs already broken in the source are carried through as warnings,
    not treated as a build failure."""
    missing_local_refs = {u["ref"] for u in unresolved if u.get("missing_local")}
    hard = []
    for failure in check_closure(reduced):
        ref = failure.rsplit(" -> ", 1)[-1].split(" ")[0]
        if ref not in missing_local_refs:
            hard.append(failure)
    if missing_local_refs:
        result["warnings"].append(
            "source contains local references that do not resolve in "
            "the source itself: " + ", ".join(sorted(missing_local_refs))
            + " (carried through, not fixable by slicing)"
        )
    if hard:
        raise SchemaError(
            "internal closure check failed on the reduced document: "
            + "; ".join(hard)
        )
