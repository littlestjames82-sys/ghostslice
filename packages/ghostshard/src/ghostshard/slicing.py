"""Read-only context slicing: owned files travel full, shared files
travel at signatures level. Python uses ast; other languages are
parser-lite (definition lines kept), stated in the bundle manifest."""
from __future__ import annotations
import ast, re

def signatures_of(text: str, language: str) -> str:
    """Return the signatures-level view of a source file.

    This is the form a shared (read-only) file takes in another
    shard's bundle: enough to code against, without the full body.
    Python files keep imports, ``def``/``class`` lines, the first
    docstring line, and uppercase constants. Other languages keep
    definition and import lines only (parser-lite). Unparseable
    Python yields an empty string.
    """
    if language == "python":
        return _py_signatures(text)
    return _lite_signatures(text)

def _py_signatures(text: str) -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""
    lines = []
    src_lines = text.splitlines()
    def docline(node):
        d = ast.get_docstring(node)
        return f'    """{d.splitlines()[0]}"""' if d else None
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.append(src_lines[node.lineno - 1].strip())
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            deco = [f"@{ast.unparse(d)}" for d in node.decorator_list]
            lines.extend(deco)
            kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            lines.append(f"{kw} {node.name}({ast.unparse(node.args)}) -> ...: ...")
            dl = docline(node)
            if dl: lines.append(dl)
        elif isinstance(node, ast.ClassDef):
            lines.append(f"class {node.name}:")
            dl = docline(node)
            if dl: lines.append(dl)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kw = "async def" if isinstance(sub, ast.AsyncFunctionDef) else "def"
                    lines.append(f"    {kw} {sub.name}({ast.unparse(sub.args)}) -> ...: ...")
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    lines.append(src_lines[node.lineno - 1].strip())
    return "\n".join(lines) + ("\n" if lines else "")

_DEF_LINE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|const|let|var|def|func|fn)\b.*$")
def _lite_signatures(text: str) -> str:
    kept = [ln for ln in text.splitlines() if _DEF_LINE.match(ln) or ln.strip().startswith(("import ", "from ", "require("))]
    return "\n".join(kept) + ("\n" if kept else "")
