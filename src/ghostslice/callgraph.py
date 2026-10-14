"""Python call graph + dead-function candidates (v0.19).

The import graph (graph.py) works at file level; this module works
at symbol level, for Python only, on the real `ast`. For every
Python file in a scan it builds the symbol table from the same
outline machinery `ghostslice symbols` uses (symslice), then walks
each function body resolving `ast.Call` nodes:

  exact      the callee is identified: a definition in the same
             file (module level, an enclosing scope, or `self.` /
             a resolved project base class), a name imported from
             another project module (resolved with graph.py's own
             module mapping), a method on a class defined in or
             imported into the file, or `module.func()` through an
             import alias.
  heuristic  a bare name with no local definition and no import
             evidence that matches a callable of the same name in
             another project file. Recorded as heuristic, never
             dressed up as exact.
  attribute  `anything.name(...)`: the receiver's type is not
             statically known, so the edge goes to every project
             method with that name. Deliberately conservative —
             this is what keeps overridden methods, protocol
             implementations, and methods called through instance
             variables from being flagged dead.

Calls that resolve to builtins or to external (non-project)
modules — and method calls on objects of unknown type whose name
matches no project method — are counted as external; calls through
local variables, parameters, subscripts, and `getattr` are
counted as unresolved.
String-based dispatch (`getattr(x, "name")`, registries keyed by
strings) is NOT traced — a function reached only that way will be
reported as a dead candidate, which is exactly why every surface
carries the honesty line: candidates are recommendations to
review, not instructions. Nothing in this module ever excludes
anything from an export.

Dead candidates: callable symbols (functions, methods, classes,
and names assigned a lambda) that are not reachable from the root
set and have no attribute-name call/reference anywhere:

  roots  module-level code of every file (import-time execution:
         a symbol called or referenced from any module top level
         is reachable), entry points at two trust levels (files
         the profile declares: their top-level callables are
         roots; files that merely look like entry points by name
         or the entries.py signals: only a function actually
         named `main` is rooted — app.py is half the world's
         Flask apps and most of its functions are not entry
         points), [project.scripts] targets from pyproject.toml,
         names exported via a module's `__all__` (plus the direct
         methods of classes so exported: a public class's methods
         are the API surface its consumers call), the contract
         entry points of a plugin module (a top-level `register`,
         or the attribute style — LANGUAGE/EXTENSIONS assignments
         plus a `slice_text` def; the plugin loader invokes them,
         so the loader is their caller), functions in
         test files and conftest.py, functions carrying a
         framework-style decorator (an attribute/call decorator,
         or one imported into the module — route handlers, pytest
         fixtures, and friends register by decoration, not by
         being called), and the methods of any class extending a
         base outside the project (an http.server handler's
         do_GET, a framework view's handlers: the external base's
         protocol invokes them). Calling a class counts as
         calling its `__init__` (its own, or an inherited project
         one), since that is what instantiation executes.
  never  dunder methods (protocol surface — Python calls them
         implicitly), anything in a test file, and anything in a
         file that does not parse (no verdict without evidence).

References count as well as calls: a function passed as a callback,
stored in a dict/list, assigned, or named in a default argument is
alive. Attribute loads count by name for methods, which keeps
properties and protocol attributes alive when they are accessed
but never called.

Caching (v1.0.2): CallGraph accepts the optional content cache
(cache.py) the export path uses. The per-file symbol outlines —
the derivation cache.py keys as "outline" — go through it with
the same discipline (content-hash keys, plugin-digest
namespacing, corrupt-never-fails), so a warm `calls` skips
re-outlining every Python file. The ast parse and the walk itself
are not cache kinds and still run per call; output is identical
either way.
"""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .graph import _py_module_base
from .symslice import Symbol, outline_source
from .tokens import METHOD as TOKEN_METHOD
from .tokens import estimate_tokens
from .textio import read_text as _gs_read_text

HONESTY = ("recommendations to review, not instructions: dynamic "
           "dispatch, getattr, string registries, and framework "
           "callbacks can hide real use")

_CALLABLE_KINDS = ("function", "method", "class")
_BUILTINS = set(dir(builtins))


# ---------------------------------------------------------------------------
# Symbol / file records
# ---------------------------------------------------------------------------

@dataclass
class _Sym:
    id: str                 # "path:Qualified.name"
    path: str
    name: str               # bare name
    qualified: str
    kind: str               # function|method|class|constant|attribute|type...
    start_line: int         # 1-based
    end_line: int
    tokens: int             # estimated
    definitions: int = 1    # >1 for shadowed / conditional redefinitions
    is_lambda: bool = False


@dataclass
class _Import:
    kind: str               # "module" | "name"
    module_base: str        # root-relative dotted->path base, "" for "."
    orig: str = ""          # for kind == "name": the imported name


@dataclass
class _ClassInfo:
    qualified: str
    bases: list[str] = field(default_factory=list)  # dotted, as written


@dataclass
class _File:
    path: str
    entry: object
    source: str
    lines: list[str]
    tree: object = None                     # ast.Module | None
    parse_ok: bool = False
    symbols: dict = field(default_factory=dict)        # qualified -> _Sym
    imports: dict = field(default_factory=dict)        # local name -> _Import
    classes: dict = field(default_factory=dict)        # qualified -> _ClassInfo
    all_names: set = field(default_factory=set)        # __all__ contents
    framework_roots: set = field(default_factory=set)  # qualified names
    lambda_names: set = field(default_factory=set)     # qualified names
    plugin_roots: set = field(default_factory=set)     # qualified names


def _dotted(node) -> str | None:
    """Dotted name for a Name/Attribute chain, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Subscript):
        return _dotted(node.value)  # Generic[T] -> Generic
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _module_file(base: str, root_files: set[str]) -> str | None:
    """Project file for a module base — graph.py's candidate shape,
    plus a unique-suffix fallback for src-layout projects: when
    `ghostslice/ledger` matches no root-relative file but exactly
    one scanned file ends with it (e.g. `src/ghostslice/ledger.py`),
    that file is the module. Ambiguous suffixes resolve to None."""
    if not base:
        return None
    for cand in (f"{base}.py", f"{base}/__init__.py"):
        if cand in root_files:
            return cand
    hits = [p for p in root_files
            if p.endswith(f"/{base}.py") or p.endswith(f"/{base}/__init__.py")]
    return hits[0] if len(hits) == 1 else None


# ---------------------------------------------------------------------------
# Per-file static facts (imports, classes, __all__, decorators)
# ---------------------------------------------------------------------------

def _collect_file_facts(fi: _File) -> None:
    tree = fi.tree
    current_dir = PurePosixPath(fi.path).parent
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    base = _py_module_base(alias.name, 0, current_dir)
                    fi.imports[alias.asname] = _Import("module", base)
                else:
                    top = alias.name.split(".")[0]
                    fi.imports[top] = _Import(
                        "module", _py_module_base(top, 0, current_dir))
        elif isinstance(node, ast.ImportFrom):
            base = _py_module_base(node.module or "", node.level or 0,
                                   current_dir)
            for alias in node.names:
                if alias.name == "*":
                    continue
                fi.imports[alias.asname or alias.name] = _Import(
                    "name", base, orig=alias.name)
    # __all__ at module level.
    for node in tree.body:
        value = None
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__"
                for t in node.targets):
            value = node.value
        elif isinstance(node, ast.AugAssign) and isinstance(
                node.target, ast.Name) and node.target.id == "__all__":
            value = node.value
        if isinstance(value, (ast.List, ast.Tuple)):
            for elt in value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    fi.all_names.add(elt.value)
    _collect_plugin_roots(fi, tree.body)
    _collect_classes(fi, tree.body, "")


# The plugin contract's entry points (plugins.py): a plugin module
# is invoked by the loader, never by project code, so its contract
# functions are roots — the loader is their caller. Detection is
# the contract itself, exactly what the loader accepts: a top-level
# `register` function, or the attribute style (module-level LANGUAGE
# and EXTENSIONS assignments plus a top-level `slice_text` def).
# Only the contract names are rooted; everything they call or
# reference becomes reachable through them as usual, and a helper
# they never touch still flags — presenting the contract makes a
# module loadable as a plugin, it does not bless its dead code.
_PLUGIN_ENTRY_POINTS = ("register", "slice_text", "outline")


def _collect_plugin_roots(fi: _File, body) -> None:
    assigned: set = set()
    defs: set = set()
    for node in body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.add(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.add(node.name)
    if "register" in defs or (
            {"LANGUAGE", "EXTENSIONS"} <= assigned
            and "slice_text" in defs):
        fi.plugin_roots = defs & set(_PLUGIN_ENTRY_POINTS)


def _collect_classes(fi: _File, body, prefix: str) -> None:
    for node in body:
        if isinstance(node, ast.ClassDef):
            q = f"{prefix}.{node.name}" if prefix else node.name
            bases = [d for d in (_dotted(b) for b in node.bases) if d]
            fi.classes[q] = _ClassInfo(q, bases)
            _collect_classes(fi, node.body, q)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            q = f"{prefix}.{node.name}" if prefix else node.name
            _collect_classes(fi, node.body, q)
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    _collect_classes(fi, [child], prefix)


def _is_framework_decorator(fi: _File, dec) -> bool:
    """Registration-style decorator: `@app.route(...)`,
    `@pytest.fixture`, `@route` imported into the module, ...

    A plain local name (`@property`, `@my_decorator`) or a local
    attribute (`@x.setter`) does not qualify on its own."""
    if isinstance(dec, ast.Call):
        if isinstance(dec.func, ast.Attribute):
            return True
        if isinstance(dec.func, ast.Name):
            return dec.func.id in fi.imports
        return False
    if isinstance(dec, ast.Attribute):
        root = dec
        while isinstance(root, ast.Attribute):
            root = root.value
        return isinstance(root, ast.Name) and root.id in fi.imports
    if isinstance(dec, ast.Name):
        return dec.id in fi.imports
    return False


# ---------------------------------------------------------------------------
# The walker: calls + references per scope
# ---------------------------------------------------------------------------

class _Walker:
    def __init__(self, cg: "CallGraph", fi: _File):
        self.cg = cg
        self.fi = fi
        self.name_stack: list[str] = []     # enclosing def/class names
        self.class_stack: list[str] = []    # enclosing class qualifieds
        self.func_stack: list[str] = []     # enclosing function qualifieds
        self.locals_stack: list[set] = []   # per-function local names
        self.globals_stack: list[set] = []  # per-function `global` names
        self.meta_stack: list[dict] = []    # per-function {first_arg,
                                            # is_classmethod, class_q}

    # -- scope helpers ---------------------------------------------------

    def _qualified(self, name: str) -> str:
        return ".".join(self.name_stack + [name]) if self.name_stack else name

    def _caller(self) -> str:
        if self.func_stack:
            return f"{self.fi.path}:{self.func_stack[-1]}"
        return f"{self.fi.path}:<module>"

    def _prefixes(self) -> list[str]:
        """Qualified prefixes to try for a bare name, innermost first."""
        out = []
        for k in range(len(self.name_stack), -1, -1):
            out.append(".".join(self.name_stack[:k]))
        return out

    def _cls_class(self, name: str) -> str | None:
        """Qualified name of the enclosing class when `name` is the
        `cls` parameter of a classmethod being walked — `cls()` is
        an instantiation and `cls.m()` a call on the class."""
        if not self.meta_stack:
            return None
        meta = self.meta_stack[-1]
        if meta["is_classmethod"] and meta["first_arg"] == name:
            return meta["class_q"]
        return None

    def _is_local(self, name: str) -> bool:
        for locals_, globals_ in zip(reversed(self.locals_stack),
                                     reversed(self.globals_stack)):
            if name in globals_:
                return False
            if name in locals_:
                return True
        return False

    # -- main dispatch ----------------------------------------------------

    def visit(self, node, suppress_ref: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._visit_function(node)
            return
        if isinstance(node, ast.ClassDef):
            self._visit_class(node)
            return
        if isinstance(node, ast.Call):
            self._handle_call(node)
            self.visit(node.func, suppress_ref=True)
            for arg in node.args:
                self.visit(arg)
            for kw in node.keywords:
                self.visit(kw.value)
            return
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load) and not suppress_ref:
                self.cg._reference_name(self, node.id)
            return
        if isinstance(node, ast.Attribute):
            if isinstance(node.ctx, ast.Load) and not suppress_ref:
                self.cg._reference_attribute(self, node)
            self.visit(node.value)
            return
        if isinstance(node, ast.Lambda):
            for default in list(node.args.defaults) + \
                    [d for d in node.args.kw_defaults if d is not None]:
                self.visit(default)
            self.visit(node.body)
            return
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
            self._visit_lambda_assign(node)
            return
        for child in ast.iter_child_nodes(node):
            self.visit(child)

    def _visit_lambda_assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self.visit(target)
        target_q = None
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            cand = self._qualified(node.targets[0].id)
            if cand in self.fi.symbols:
                target_q = cand
                self.fi.lambda_names.add(cand)
        lam = node.value
        for default in list(lam.args.defaults) + \
                [d for d in lam.args.kw_defaults if d is not None]:
            self.visit(default)
        if target_q is not None:
            self.func_stack.append(target_q)
            self.locals_stack.append(_collect_locals(lam))
            self.globals_stack.append(set())
            self.visit(lam.body)
            self.func_stack.pop()
            self.locals_stack.pop()
            self.globals_stack.pop()
        else:
            self.visit(lam.body)

    def _visit_function(self, node) -> None:
        q = self._qualified(node.name)
        # Decorators, defaults, and annotations evaluate in the
        # enclosing scope.
        for dec in node.decorator_list:
            if _is_framework_decorator(self.fi, dec):
                self.fi.framework_roots.add(q)
            self.visit(dec)
        for default in list(node.args.defaults) + \
                [d for d in node.args.kw_defaults if d is not None]:
            self.visit(default)
        if node.returns is not None:
            self.visit(node.returns)
        for arg in _all_args(node.args):
            if arg.annotation is not None:
                self.visit(arg.annotation)
        args = _all_args(node.args)
        is_classmethod = any(
            (_dotted(d) or "").split(".")[-1] == "classmethod"
            for d in node.decorator_list)
        self.name_stack.append(node.name)
        self.func_stack.append(q)
        self.locals_stack.append(_collect_locals(node))
        self.globals_stack.append(_collect_globals(node))
        self.meta_stack.append({
            "first_arg": args[0].arg if args else None,
            "is_classmethod": is_classmethod,
            "class_q": self.class_stack[-1] if self.class_stack else None,
        })
        for stmt in node.body:
            self.visit(stmt)
        self.name_stack.pop()
        self.func_stack.pop()
        self.locals_stack.pop()
        self.globals_stack.pop()
        self.meta_stack.pop()

    def _visit_class(self, node: ast.ClassDef) -> None:
        q = self._qualified(node.name)
        for dec in node.decorator_list:
            self.visit(dec)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw.value)
        self.name_stack.append(node.name)
        self.class_stack.append(q)
        for stmt in node.body:
            self.visit(stmt)
        self.name_stack.pop()
        self.class_stack.pop()

    # -- call resolution ---------------------------------------------------

    def _handle_call(self, node: ast.Call) -> None:
        cg = self.cg
        fi = self.fi
        cg.counts["calls"] += 1
        caller = self._caller()
        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
            hit = self._resolve_bare(name)
            if hit is not None:
                kind, target = hit
                cg._add_call_edge(caller, target, kind)
            elif self._cls_class(name) is not None:
                cls_sym = fi.symbols.get(self._cls_class(name))
                if cls_sym is not None:
                    cg._add_call_edge(caller, cls_sym.id, "exact")
                else:
                    cg.counts["unresolved"] += 1
            elif self._is_local(name):
                cg.counts["unresolved"] += 1
            elif name in _BUILTINS:
                cg.counts["external"] += 1
            else:
                targets = cg.callables_by_name.get(name, [])
                targets = [t for t in targets
                           if not t.startswith(fi.path + ":")]
                if targets:
                    for t in targets:
                        cg._add_call_edge(caller, t, "heuristic")
                else:
                    cg.counts["unresolved"] += 1
            return
        if isinstance(func, ast.Attribute):
            self._handle_attribute_call(node, func, caller)
            return
        cg.counts["unresolved"] += 1

    def _resolve_bare(self, name: str):
        """(kind, symbol id) for a bare-name call, or None.

        Scope chain first (nested defs, recursion), then module
        level, then import evidence — imports outrank the builtin
        check because a project may shadow a builtin name."""
        fi = self.fi
        for prefix in self._prefixes():
            cand = f"{prefix}.{name}" if prefix else name
            sym = fi.symbols.get(cand)
            if sym is not None and (sym.kind in _CALLABLE_KINDS
                                    or cand in fi.lambda_names):
                return "exact", sym.id
        imp = fi.imports.get(name)
        if imp is not None:
            if imp.kind == "name":
                target = self.cg._import_target(fi, imp, imp.orig)
                if target is not None:
                    return "exact", target
                if imp.module_base and _module_file(
                        imp.module_base, self.cg.root_files) is None:
                    return "external", None  # imported from a package
                    # outside the project: the call leaves the graph
            return None
        return None

    def _handle_attribute_call(self, node: ast.Call, func: ast.Attribute,
                               caller: str) -> None:
        cg = self.cg
        fi = self.fi
        attr = func.attr
        recv = func.value
        target = None
        # super().attr(...)
        poly_cls = None  # enclosing class for polymorphic fan-out
        if isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name) \
                and recv.func.id == "super":
            target = self._resolve_on_bases(attr)
        elif isinstance(recv, ast.Name) and recv.id == "self":
            target = self._resolve_on_self(attr)
            poly_cls = self.class_stack[-1] if self.class_stack else None
        elif isinstance(recv, ast.Name) and \
                self._cls_class(recv.id) is not None:
            cls_q = self._cls_class(recv.id)
            sym = fi.symbols.get(f"{cls_q}.{attr}")
            target = sym.id if sym is not None else \
                cg._resolve_base_method(fi, cls_q, attr, set())
            poly_cls = cls_q
        elif isinstance(recv, ast.Name):
            target = self._resolve_on_name(recv.id, attr)
        if target:
            cg._add_edge(caller, target, "exact")
            if poly_cls is not None:
                # self.m() dispatches on the runtime type: subclass
                # overrides are call targets too (template-method
                # pattern — audit G14 F6).
                for other in cg._descendant_overrides(fi.path, poly_cls,
                                                      attr, target):
                    cg._add_edge(caller, other, "attribute")
            return
        if isinstance(recv, ast.Name) and recv.id in fi.imports:
            imp = fi.imports[recv.id]
            if imp.kind == "module" and imp.module_base and \
                    _module_file(imp.module_base, cg.root_files) is None:
                cg.counts["external"] += 1
                return
        methods = cg.methods_by_name.get(attr, [])
        if methods:
            for t in methods:
                cg._add_edge(caller, t, "attribute")
        else:
            # A method call on an object of unknown type whose name
            # matches no project method: the call leaves the project
            # (stdlib/external object) in the overwhelming majority.
            cg.counts["external"] += 1

    def _resolve_on_self(self, attr: str):
        if not self.class_stack:
            return None
        fi = self.fi
        cls_q = self.class_stack[-1]
        sym = fi.symbols.get(f"{cls_q}.{attr}")
        if sym is not None:
            return sym.id
        return self.cg._resolve_base_method(fi, cls_q, attr, set())

    def _resolve_on_bases(self, attr: str):
        if not self.class_stack:
            return None
        return self.cg._resolve_base_method(
            self.fi, self.class_stack[-1], attr, set())

    def _resolve_on_name(self, name: str, attr: str):
        """`Name.attr(...)`: Name is a class in scope, an imported
        class, or an imported module alias."""
        fi = self.fi
        cg = self.cg
        # Class defined in this file (module level or enclosing scope).
        for prefix in self._prefixes():
            cand = f"{prefix}.{name}" if prefix else name
            sym = fi.symbols.get(cand)
            if sym is not None and sym.kind == "class":
                member = fi.symbols.get(f"{cand}.{attr}")
                if member is not None:
                    return member.id
                return cg._resolve_base_method(fi, cand, attr, set())
        imp = fi.imports.get(name)
        if imp is not None:
            if imp.kind == "module":
                path = _module_file(imp.module_base, cg.root_files)
                if path is not None:
                    tfi = cg.files.get(path)
                    if tfi is not None:
                        sym = tfi.symbols.get(attr)
                        if sym is not None:
                            return sym.id
                return None
            # from M import Name — a class (or module) from M.
            target = cg._import_target(fi, imp, imp.orig)
            if target is not None:
                tfi = cg.files.get(target.split(":", 1)[0])
                if tfi is not None and target.endswith(":" + imp.orig):
                    member = tfi.symbols.get(f"{imp.orig}.{attr}")
                    if member is not None:
                        return member.id
                    return cg._resolve_base_method(tfi, imp.orig, attr, set())
                return None  # imported a function and called .attr on it
            # from M import submodule — submodule.attr()
            sub = _module_file(
                f"{imp.module_base}/{imp.orig}" if imp.module_base
                else imp.orig, cg.root_files)
            if sub is not None:
                tfi = cg.files.get(sub)
                if tfi is not None:
                    sym = tfi.symbols.get(attr)
                    if sym is not None:
                        return sym.id
            return None
        return None


def _all_args(arguments) -> list:
    out = list(arguments.posonlyargs) + list(arguments.args) \
        + list(arguments.kwonlyargs)
    if arguments.vararg is not None:
        out.append(arguments.vararg)
    if arguments.kwarg is not None:
        out.append(arguments.kwarg)
    return out


def _collect_locals(func) -> set:
    """Names bound inside one function body (not nested scopes):
    parameters, stores, def/class names, import bindings, except
    handler names, comprehension targets."""
    names: set = set()
    args = getattr(func, "args", None)
    if args is not None:
        for arg in _all_args(args):
            names.add(arg.arg)
    body = func.body if isinstance(func.body, list) else [func.body]

    def walk(node) -> None:
        # Any def/class/lambda met here is a NESTED scope: its name
        # is a local of this function, its body is not.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names.add(node.name)
            return
        if isinstance(node, ast.Lambda):
            return
        if isinstance(node, ast.Name) and isinstance(
                node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        for child in ast.iter_child_nodes(node):
            walk(child)

    for stmt in body:
        walk(stmt)
    return names


def _collect_globals(func) -> set:
    out: set = set()
    body = func.body if isinstance(func.body, list) else [func.body]

    def walk(node) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef, ast.Lambda)):
            return  # a nested scope's `global` is its own
        if isinstance(node, ast.Global):
            out.update(node.names)
        for child in ast.iter_child_nodes(node):
            walk(child)

    for stmt in body:
        walk(stmt)
    return out


# ---------------------------------------------------------------------------
# The graph itself
# ---------------------------------------------------------------------------

class CallGraph:
    def __init__(self, scan_result, profile=None, graph=None, cache=None):
        self.scan_result = scan_result
        self.profile = profile
        # v1.0.2: optional cache.ProjectCache for the per-file
        # outlines (see module docstring); None = always recompute.
        self.cache = cache
        self.root_files = {f.path for f in scan_result.files}
        self.files: dict[str, _File] = {}
        self.symbols: dict[str, _Sym] = {}
        self.methods_by_name: dict[str, list[str]] = {}
        self.callables_by_name: dict[str, list[str]] = {}
        self.edges: dict[tuple, int] = {}   # (caller, callee, kind) -> sites
        self.attr_ref_names: set = set()
        self.counts = {"calls": 0, "exact": 0, "heuristic": 0,
                       "attribute": 0, "references": 0,
                       "unresolved": 0, "external": 0}
        self.skipped_files: list[str] = []
        self._build(graph)

    # -- construction ------------------------------------------------------

    def _build(self, graph) -> None:
        py_entries = [e for e in self.scan_result.files
                      if e.language == "python"]
        for entry in py_entries:
            fi = self._load_file(entry)
            if fi is not None:
                self.files[entry.path] = fi
        for fi in self.files.values():
            for sym in fi.symbols.values():
                self.symbols[sym.id] = sym
                if sym.kind == "method":
                    self.methods_by_name.setdefault(sym.name, []).append(sym.id)
                if sym.kind in _CALLABLE_KINDS:
                    self.callables_by_name.setdefault(sym.name, []).append(sym.id)
        # Project class hierarchy (base id -> subclass ids) for
        # polymorphic fan-out of self./cls. calls.
        self.subclasses: dict[str, set] = {}
        for fi in self.files.values():
            for cls_q, info in fi.classes.items():
                child_id = f"{fi.path}:{cls_q}"
                for base in info.bases:
                    bfi, bq = self._resolve_class(fi, base)
                    if bfi is not None and bq is not None:
                        self.subclasses.setdefault(
                            f"{bfi.path}:{bq}", set()).add(child_id)
        for fi in self.files.values():
            walker = _Walker(self, fi)
            for stmt in fi.tree.body:
                walker.visit(stmt)
        for (caller, callee, kind), sites in list(self.edges.items()):
            if kind in self.counts:
                self.counts[kind] += sites

    def _load_file(self, entry) -> _File | None:
        try:
            source = _gs_read_text(entry.abspath)
        except OSError:
            source = ""
        fi = _File(path=entry.path, entry=entry, source=source,
                   lines=source.splitlines())
        try:
            fi.tree = ast.parse(source)
            fi.parse_ok = True
        except Exception:
            self.skipped_files.append(entry.path)
            return None
        outline = self._outline(entry, source)
        for sym in outline:
            if not sym.selectable:
                continue
            seg = "\n".join(fi.lines[sym.start:sym.end + 1])
            rec = _Sym(
                id=f"{entry.path}:{sym.qualified}", path=entry.path,
                name=sym.name, qualified=sym.qualified, kind=sym.kind,
                start_line=sym.start + 1, end_line=sym.end + 1,
                tokens=estimate_tokens(seg, "python"))
            prev = fi.symbols.get(sym.qualified)
            if prev is not None:
                # Redefinition (shadowing, if/else branches): the
                # name is one symbol; the last definition's span is
                # the live one.
                rec.definitions = prev.definitions + 1
            fi.symbols[sym.qualified] = rec
        _collect_file_facts(fi)
        return fi

    def _outline(self, entry, source: str) -> list:
        """The file's symbol outline, through the content cache
        when one is attached: the same get/put seam
        symslice.resolve_symbol_selection uses (rows are the
        Symbol dataclass as dicts; a shape drift on read falls
        back to recompute, never to a wrong outline)."""
        if self.cache is not None:
            rows = self.cache.get_outline(entry.path, source)
            if rows is not None:
                try:
                    return [Symbol(**row) for row in rows]
                except TypeError:
                    pass  # shape drift: recompute below
        syms = outline_source(source, "python", entry.path)
        if self.cache is not None and syms is not None:
            from dataclasses import asdict
            self.cache.put_outline(entry.path, source,
                                   [asdict(s) for s in syms])
        return syms or []

    # -- cross-file resolution helpers --------------------------------------

    def _import_target(self, fi: _File, imp: _Import, orig: str):
        """Symbol id for `from <imp> import orig`, or None."""
        path = _module_file(imp.module_base, self.root_files)
        if path is None:
            return None
        tfi = self.files.get(path)
        if tfi is None:
            return None
        sym = tfi.symbols.get(orig)
        if sym is not None:
            return sym.id
        return None

    def _resolve_base_method(self, fi: _File, cls_q: str, attr: str,
                             seen: set):
        """Method `attr` on a project base class of `cls_q`."""
        if cls_q in seen:
            return None
        seen.add(cls_q)
        info = fi.classes.get(cls_q)
        if info is None:
            return None
        for base in info.bases:
            bfi, bq = self._resolve_class(fi, base)
            if bfi is None or bq is None:
                continue
            sym = bfi.symbols.get(f"{bq}.{attr}")
            if sym is not None:
                return sym.id
            hit = self._resolve_base_method(bfi, bq, attr, seen)
            if hit is not None:
                return hit
        return None

    def _resolve_class(self, fi: _File, dotted: str):
        """(file, qualified) for a class named by a dotted string."""
        parts = dotted.split(".")
        name = parts[-1]
        if len(parts) > 1:
            root = parts[0]
            imp = fi.imports.get(root)
            if imp is not None and imp.kind == "module":
                base = imp.module_base
                for extra in parts[1:-1]:
                    base = f"{base}/{extra}" if base else extra
                path = _module_file(base, self.root_files)
                if path is not None:
                    tfi = self.files.get(path)
                    if tfi is not None and name in {
                            s.name for s in tfi.symbols.values()
                            if s.kind == "class"}:
                        for s in tfi.symbols.values():
                            if s.kind == "class" and s.name == name:
                                return tfi, s.qualified
                return None, None
        sym = fi.symbols.get(name)
        if sym is not None and sym.kind == "class":
            return fi, name
        imp = fi.imports.get(name)
        if imp is not None and imp.kind == "name":
            target = self._import_target(fi, imp, imp.orig)
            if target is not None:
                tfi = self.files.get(target.split(":", 1)[0])
                if tfi is not None:
                    return tfi, imp.orig
        return None, None

    def _descendant_overrides(self, path: str, cls_q: str, attr: str,
                              exclude: str | None) -> list[str]:
        """Method symbols named `attr` in subclasses (transitively)
        of the given class — the polymorphic dispatch targets of a
        `self.attr()` / `cls.attr()` call."""
        out: list[str] = []
        seen = {f"{path}:{cls_q}"}
        stack = [f"{path}:{cls_q}"]
        while stack:
            cur = stack.pop()
            for child in self.subclasses.get(cur, ()):
                if child in seen:
                    continue
                seen.add(child)
                stack.append(child)
                cpath, cq = child.split(":", 1)
                tfi = self.files.get(cpath)
                if tfi is None:
                    continue
                sym = tfi.symbols.get(f"{cq}.{attr}")
                if sym is not None and sym.id != exclude:
                    out.append(sym.id)
        return out

    # -- references -----------------------------------------------------------

    def _add_edge(self, caller: str, callee: str | None, kind: str) -> None:
        if callee is None:
            if kind == "external":
                self.counts["external"] += 1
            return
        key = (caller, callee, kind)
        self.edges[key] = self.edges.get(key, 0) + 1

    def _add_call_edge(self, caller: str, callee: str, kind: str) -> None:
        """A resolved CALL edge. Calling a class is calling its
        `__init__`: without this second edge the constructor's whole
        downstream subtree (everything __init__ wires up) looks
        unreachable — audit G14 F1."""
        self._add_edge(caller, callee, kind)
        sym = self.symbols.get(callee)
        if sym is None or sym.kind != "class":
            return
        tfi = self.files.get(sym.path)
        if tfi is None:
            return
        init = tfi.symbols.get(f"{sym.qualified}.__init__")
        if init is not None:
            self._add_edge(caller, init.id, kind)
            return
        inherited = self._resolve_base_method(tfi, sym.qualified,
                                              "__init__", set())
        if inherited is not None:
            self._add_edge(caller, inherited, kind)

    def _reference_name(self, walker: _Walker, name: str) -> None:
        fi = walker.fi
        for prefix in walker._prefixes():
            cand = f"{prefix}.{name}" if prefix else name
            sym = fi.symbols.get(cand)
            if sym is not None:
                self._add_edge(walker._caller(), sym.id, "reference")
                return
        imp = fi.imports.get(name)
        if imp is not None and imp.kind == "name":
            target = self._import_target(fi, imp, imp.orig)
            if target is not None:
                self._add_edge(walker._caller(), target, "reference")

    def _reference_attribute(self, walker: _Walker, node: ast.Attribute) -> None:
        self.attr_ref_names.add(node.attr)
        fi = walker.fi
        recv = node.value
        if isinstance(recv, ast.Name) and recv.id == "self" \
                and walker.class_stack:
            sym = fi.symbols.get(f"{walker.class_stack[-1]}.{node.attr}")
            if sym is not None:
                self._add_edge(walker._caller(), sym.id, "reference")
                return
        if isinstance(recv, ast.Name):
            imp = fi.imports.get(recv.id)
            if imp is not None and imp.kind == "module":
                path = _module_file(imp.module_base, self.root_files)
                if path is not None:
                    tfi = self.files.get(path)
                    if tfi is not None:
                        sym = tfi.symbols.get(node.attr)
                        if sym is not None:
                            self._add_edge(walker._caller(), sym.id,
                                           "reference")

    # -- roots + reachability --------------------------------------------------

    def root_ids(self, graph=None) -> set:
        roots: set = set()
        # Module top levels always execute on import.
        for path in self.files:
            roots.add(f"{path}:<module>")
        by_path = {e.path: e for e in self.scan_result.files}
        # Entry points, two trust levels. Files the PROFILE declares
        # are trusted fully: their top-level callables are roots.
        # Merely heuristic files (main.py / app.py / cli.py ... —
        # app.py is half the world's Flask apps, and most of its
        # functions are not entry points) root only a function
        # actually named `main`; the rest must earn reachability
        # through the __main__ block's module-level edges like
        # everything else (audit G14 F3).
        declared = [p for p in (self.profile.entry_points
                                if self.profile else [])
                    if p in self.files]
        for path in declared:
            for sym in self.files[path].symbols.values():
                if sym.kind in ("function", "class") \
                        and "." not in sym.qualified:
                    roots.add(sym.id)
        entry_files: set = set()
        try:
            from .graph import find_entry_points
            entry_files.update(find_entry_points(self.scan_result,
                                                 self.profile))
        except Exception:
            pass
        try:
            from .entries import find_entry_candidates
            entry_files.update(
                c["path"] for c in find_entry_candidates(
                    self.scan_result, graph))
        except Exception:
            pass
        for path in entry_files:
            fi = self.files.get(path)
            if fi is None:
                continue
            sym = fi.symbols.get("main")
            if sym is not None and sym.kind == "function":
                roots.add(sym.id)
        # [project.scripts] targets: module:attr.
        try:
            from .entries import _pyproject_scripts
            root = Path(self.scan_result.root)
            for _cmd, target in _pyproject_scripts(root).items():
                module, _, attr = target.partition(":")
                if not module or not attr:
                    continue
                base = module.replace(".", "/")
                for cand in (f"{base}.py", f"{base}/__init__.py",
                             f"src/{base}.py", f"src/{base}/__init__.py"):
                    fi = self.files.get(cand)
                    if fi is not None:
                        sym = fi.symbols.get(attr)
                        if sym is not None:
                            roots.add(sym.id)
                        break
        except Exception:
            pass
        for fi in self.files.values():
            entry = by_path.get(fi.path)
            is_test = bool(entry and entry.is_test) or \
                PurePosixPath(fi.path).name == "conftest.py"
            exported_classes = {
                sym.qualified for sym in fi.symbols.values()
                if sym.kind == "class" and sym.name in fi.all_names
                and "." not in sym.qualified}
            for sym in fi.symbols.values():
                if sym.qualified in fi.framework_roots:
                    roots.add(sym.id)
                if sym.qualified in fi.plugin_roots:
                    roots.add(sym.id)
                if sym.name in fi.all_names and "." not in sym.qualified:
                    roots.add(sym.id)
                if sym.kind == "method" and "." in sym.qualified:
                    # A class named in __all__ is public API: its
                    # direct methods are the surface consumers call
                    # (the PluginAPI a plugin's register() receives
                    # is the canonical case), so they are roots,
                    # not dead code.
                    parent = sym.qualified.rsplit(".", 1)[0]
                    if parent in exported_classes:
                        roots.add(sym.id)
                if is_test and sym.kind in ("function", "method"):
                    roots.add(sym.id)
            # A class extending a base outside the project (an
            # http.server handler, a framework view, an Exception)
            # has its methods invoked by that external protocol:
            # they are entry points, not dead code (audit G14 F2).
            for cls_q, info in fi.classes.items():
                if not info.bases:
                    continue
                if all(self._resolve_class(fi, b)[0] is not None
                       for b in info.bases):
                    continue  # every base is a project class
                prefix = cls_q + "."
                for sym in fi.symbols.values():
                    if sym.kind == "method" \
                            and sym.qualified.startswith(prefix) \
                            and "." not in sym.qualified[len(prefix):]:
                        roots.add(sym.id)
        return roots

    def reachable(self, graph=None) -> set:
        adjacency: dict[str, set] = {}
        for (caller, callee, _kind) in self.edges:
            adjacency.setdefault(caller, set()).add(callee)
        seen: set = set()
        stack = list(self.root_ids(graph))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adjacency.get(cur, ()))
        return seen

    # -- dead candidates ---------------------------------------------------------

    def dead_candidates(self, graph=None) -> list[dict]:
        seen = self.reachable(graph)
        # Direct self-recursion is use: a function whose only caller
        # is itself is recursive, not dead (mutually-recursive
        # clusters get no such pass — reachability decides those).
        self_edged = {callee for (caller, callee, kind) in self.edges
                      if caller == callee and kind != "reference"}
        by_path = {e.path: e for e in self.scan_result.files}
        out: list[dict] = []
        for sym in self.symbols.values():
            if sym.id in seen or sym.id in self_edged:
                continue
            kind = sym.kind
            if kind == "constant" and sym.qualified in \
                    self.files[sym.path].lambda_names:
                kind = "function"
            if kind not in _CALLABLE_KINDS:
                continue
            if sym.name.startswith("__") and sym.name.endswith("__"):
                continue  # dunder: protocol surface, implicitly called
            entry = by_path.get(sym.path)
            if entry is not None and entry.is_test:
                continue
            if PurePosixPath(sym.path).name == "conftest.py":
                continue
            if kind == "method" and sym.name in self.attr_ref_names:
                continue  # accessed as an attribute somewhere (property…)
            out.append({
                "id": sym.id, "path": sym.path, "name": sym.name,
                "qualified": sym.qualified, "kind": kind,
                "start_line": sym.start_line, "end_line": sym.end_line,
                "tokens": sym.tokens,
            })
        out.sort(key=lambda d: (-d["tokens"], d["path"], d["start_line"]))
        return out

    # -- payload -------------------------------------------------------------------

    def payload(self, graph=None) -> dict:
        fan_in: dict[str, int] = {}
        ref_in: dict[str, int] = {}
        for (caller, callee, kind), sites in self.edges.items():
            if kind == "reference":
                ref_in[callee] = ref_in.get(callee, 0) + sites
            else:
                fan_in[callee] = fan_in.get(callee, 0) + sites
        symbols = []
        for sym in sorted(self.symbols.values(),
                          key=lambda s: (s.path, s.start_line)):
            kind = sym.kind
            fi = self.files[sym.path]
            if kind == "constant" and sym.qualified in fi.lambda_names:
                kind = "function"
            symbols.append({
                "id": sym.id, "path": sym.path, "name": sym.name,
                "qualified": sym.qualified, "kind": kind,
                "start_line": sym.start_line, "end_line": sym.end_line,
                "tokens": sym.tokens,
                "fan_in": fan_in.get(sym.id, 0),
                "references": ref_in.get(sym.id, 0),
            })
        edges = [{"caller": c, "callee": t, "kind": k, "sites": s}
                 for (c, t, k), s in sorted(self.edges.items())]
        counts = dict(self.counts)
        counts["references"] = sum(
            s for (_c, _t, k), s in self.edges.items() if k == "reference")
        counts["symbols"] = len(self.symbols)
        counts["files"] = len(self.files)
        return {
            "root": str(self.scan_result.root),
            "symbols": symbols,
            "edges": edges,
            "dead": self.dead_candidates(graph),
            "counts": counts,
            "skipped_files": list(self.skipped_files),
            "token_method": TOKEN_METHOD,
            "note": HONESTY,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_call_graph(scan_result, profile=None, graph=None,
                     cache=None) -> dict:
    """Full call-graph payload for a scan (Python files only).

    `cache` (v1.0.2): an optional cache.ProjectCache for the
    per-file outlines; output is identical either way."""
    return CallGraph(scan_result, profile, graph, cache).payload(graph)


def dead_symbol_recommendations(scan_result, profile=None,
                                graph=None, cache=None) -> list[dict]:
    """Prune-recommendation-shaped dead-symbol candidates.

    Merged into the `scan` / `graph` command surfaces by the CLI;
    graph.recommendations itself (and lint, which consumes it) is
    unchanged."""
    cg = CallGraph(scan_result, profile, graph, cache)
    out = []
    for d in cg.dead_candidates(graph):
        out.append({
            "path": d["path"],
            "tokens": d["tokens"],
            "potential_savings": d["tokens"],
            "reason": (f"possibly dead symbol: {d['qualified']} "
                       f"({d['kind']}, lines {d['start_line']}-"
                       f"{d['end_line']}) — no callers or references "
                       "found in the project"),
            "detail": HONESTY,
            "importers": [],
            "kind": "dead-symbol",
            "symbol": d["qualified"],
            "lines": [d["start_line"], d["end_line"]],
        })
    out.sort(key=lambda r: r["tokens"], reverse=True)
    return out
