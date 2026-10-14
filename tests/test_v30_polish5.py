"""v1.0.5 polish round 5: lite-language depth pass 2 (Rust type
`where` clauses, C# records + Allman braces + expression-bodied
methods, PHP 8 enums), MCP parity for read-only insights
(project_graph, project_history, doctor), and the README ->
README + docs/ extraction.

Contracts:
- A Rust trait/struct whose block brace follows a multi-line
  `where` clause spans its whole body; trait methods enumerate
  (and select) like any other trait's. `;`-terminated Rust type
  declarations (unit/tuple structs) keep their statement spans.
- C# records are named correctly (`record struct Point` is
  "Point", never "struct"), enumerate their members like
  classes, and outline with true spans under Allman braces (the
  C# default) as well as K&R. Expression-bodied methods are
  symbols and survive signatures mode verbatim. Constructors
  stay non-symbols.
- A PHP enum is a declaration type: it renders whole in
  signatures/interfaces modes (its cases are its surface), its
  cases are named constants in the outline, and `case` lines
  anywhere else (switch bodies) are never symbols.
- The MCP surface carries the CLI's read-only insights with
  summary payloads and caps (graph adjacency capped at 100
  files, history per-run detail capped at 50, no raw ledger
  records). Doctor's checks are read-only and ride along.
- The README is a landing page (< the L001 threshold) and every
  relative link across README + docs/ resolves, file and anchor.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.mcp_server import handle_message
from ghostslice.slicer import slice_text
from ghostslice.symslice import outline_source, slice_with_symbols
from ghostslice.tokens import estimate_tokens

REPO = Path(__file__).resolve().parents[1]


def _outline(src, lang, name="x"):
    return {s.qualified: s for s in outline_source(src, lang, name) or []}


def _call(name, arguments):
    resp = handle_message({"jsonrpc": "2.0", "id": 1,
                           "method": "tools/call",
                           "params": {"name": name,
                                      "arguments": arguments}})
    result = resp["result"]
    if result.get("isError"):
        return None, result["content"][0]["text"]
    return json.loads(result["content"][0]["text"]), None


# ---------------------------------------------------------------------------
# Item A — Rust type `where` clauses
# ---------------------------------------------------------------------------

RUST_WHERE = """\
pub trait Greeter
where
    Self: Sized,
{
    fn name(&self) -> &str;

    fn greet(&self) -> String {
        format!("hello {}", self.name())
    }
}

pub struct Pair<T>
where
    T: Clone,
{
    value: T,
}

pub struct Unit;

pub struct Point(i32, i32);
"""


class TestRustTypeWhere:
    def test_trait_methods_enumerate(self):
        out = _outline(RUST_WHERE, "rust", "lib.rs")
        assert out["Greeter"].kind == "type"
        assert out["Greeter.name"].parent == "Greeter"
        assert out["Greeter.greet"].parent == "Greeter"

    def test_trait_span_covers_whole_body(self):
        out = _outline(RUST_WHERE, "rust", "lib.rs")
        lines = RUST_WHERE.splitlines()
        assert lines[out["Greeter"].start] == "pub trait Greeter"
        assert lines[out["Greeter"].end] == "}"
        # greet's body is inside the trait span, not a free function
        assert out["Greeter"].start < out["Greeter.greet"].start
        assert out["Greeter.greet"].end <= out["Greeter"].end

    def test_struct_span_covers_body(self):
        out = _outline(RUST_WHERE, "rust", "lib.rs")
        lines = RUST_WHERE.splitlines()
        assert lines[out["Pair"].end] == "}"
        assert out["Pair"].end > out["Pair"].start + 3

    def test_statement_types_keep_statement_spans(self):
        out = _outline(RUST_WHERE, "rust", "lib.rs")
        assert out["Unit"].start == out["Unit"].end
        assert out["Point"].start == out["Point"].end

    def test_selection_ships_trait_method(self):
        text = slice_with_symbols("lib.rs", RUST_WHERE, {"Greeter.greet"})
        assert "fn greet" in text and "format!" in text

    def test_signatures_render_whole_trait_and_struct(self):
        out = slice_text("lib.rs", RUST_WHERE, "signatures").text
        assert "pub trait Greeter" in out
        assert "where" in out and "Self: Sized," in out
        assert "fn name(&self) -> &str;" in out
        assert "pub struct Pair<T>" in out and "value: T," in out
        # statement types are surface too, kept verbatim
        assert "pub struct Unit;" in out
        assert "pub struct Point(i32, i32);" in out

    def test_braces_in_strings_do_not_extend_spans(self):
        src = RUST_WHERE + """
pub trait Tricky
where
    Self: Sized,
{
    fn brace(&self) -> &str {
        "}"
    }
}

pub fn after() -> bool {
    true
}
"""
        out = _outline(src, "rust", "lib.rs")
        assert out["Tricky.brace"].parent == "Tricky"
        assert out["after"].parent is None
        assert out["Tricky"].end < out["after"].start


# ---------------------------------------------------------------------------
# Item A — C# records, Allman braces, expression-bodied methods
# ---------------------------------------------------------------------------

CS_ALLMAN = """\
using System;

public class Control
{
    public int Work() => 42;

    public string Label() => $"count: {Count}";

    public int Count { get; set; }
}

public record Person(string FirstName, string LastName)
{
    public void Rename(string first)
    {
        Console.WriteLine(first);
    }
}

public readonly record struct Point(int X, int Y)
{
    public double Length() => Math.Sqrt(X * X + Y * Y);
}

public record class Order(int Id)
{
    public decimal Total() => 1.5m;
}

public record Marker(int Id);
"""

CS_KR = """\
using System;

public class Shapes {
    public double Area() {
        return 1.0;
    }

    public double Perimeter() => 4.0;
}

public record Person(string FirstName, string LastName) {
    public void Rename(string first) {
        Console.WriteLine(first);
    }

    public Person(string first) : this(first, "") {
    }
}
"""


class TestCSharpRecords:
    def test_record_struct_and_class_are_named_correctly(self):
        out = _outline(CS_ALLMAN, "csharp", "r.cs")
        assert "Point" in out and "struct" not in out
        assert "Order" in out and "class" not in out
        assert out["Point"].kind == "type"
        assert out["Marker"].start == out["Marker"].end

    def test_allman_spans_are_true(self):
        out = _outline(CS_ALLMAN, "csharp", "r.cs")
        lines = CS_ALLMAN.splitlines()
        assert lines[out["Control"].end] == "}"
        assert lines[out["Person"].end] == "}"
        rename = out["Person.Rename"]
        assert rename.parent == "Person"
        assert lines[rename.end] == "    }"

    def test_record_members_enumerate(self):
        out = _outline(CS_ALLMAN, "csharp", "r.cs")
        assert out["Order.Total"].parent == "Order"
        assert out["Point.Length"].parent == "Point"

    def test_expression_bodied_methods_are_symbols(self):
        out = _outline(CS_ALLMAN, "csharp", "r.cs")
        assert out["Control.Work"].kind == "method"
        # interpolation braces do not extend the span
        label = out["Control.Label"]
        assert label.start == label.end

    def test_expression_bodied_methods_survive_signatures(self):
        out = slice_text("r.cs", CS_ALLMAN, "signatures").text
        assert "public int Work() => 42;" in out
        assert 'public string Label() => $"count: {Count}";' in out
        assert "public record Marker(int Id);" in out

    def test_kr_parity_and_constructor_not_a_symbol(self):
        out = _outline(CS_KR, "csharp", "r.cs")
        assert out["Shapes.Area"].parent == "Shapes"
        assert out["Shapes.Perimeter"].parent == "Shapes"
        assert out["Person.Rename"].parent == "Person"
        # the constructor (block-bodied and expression-free) and
        # the positional parameters never become symbols
        assert "Person.Person" not in out
        sig = slice_text("r.cs", CS_KR, "signatures").text
        assert "public double Perimeter() => 4.0;" in sig
        assert "public double Area() { /* ... */ }" in sig

    def test_selection_reaches_record_method(self):
        text = slice_with_symbols("r.cs", CS_ALLMAN, {"Person.Rename"})
        assert "Rename" in text and "Console.WriteLine" in text


# ---------------------------------------------------------------------------
# Item A — PHP 8 enums
# ---------------------------------------------------------------------------

PHP_ENUM = """\
<?php

interface HasLabel
{
    public function label(): string;
}

enum Suit: string implements HasLabel
{
    case Hearts = 'H';
    case Diamonds = 'D';

    public function label(): string
    {
        return match ($this) {
            Suit::Hearts => 'Hearts',
            Suit::Diamonds => 'Diamonds',
        };
    }
}

class Deck
{
    public function pick($x)
    {
        switch ($x) {
            case 1:
                return 'one';
            default:
                return 'other';
        }
    }
}
"""


class TestPhpEnum:
    def test_enum_is_a_declaration_type(self):
        out = _outline(PHP_ENUM, "php", "s.php")
        assert out["Suit"].kind == "type"

    def test_cases_are_named_constants(self):
        out = _outline(PHP_ENUM, "php", "s.php")
        assert out["Suit.Hearts"].kind == "constant"
        assert out["Suit.Hearts"].parent == "Suit"
        assert out["Suit.Diamonds"].parent == "Suit"
        assert out["Suit.label"].kind == "method"

    def test_switch_cases_are_never_symbols(self):
        out = _outline(PHP_ENUM, "php", "s.php")
        assert not any(q.startswith("Deck.1") or q.endswith(".one")
                       for q in out)
        assert "Deck.pick" in out

    def test_signatures_and_interfaces_keep_cases(self):
        for mode in ("signatures", "interfaces"):
            out = slice_text("s.php", PHP_ENUM, mode).text
            assert "enum Suit: string implements HasLabel" in out
            assert "case Hearts = 'H';" in out
            assert "case Diamonds = 'D';" in out

    def test_case_selection_resolves(self):
        text = slice_with_symbols("s.php", PHP_ENUM, {"Suit.Hearts"})
        assert "case Hearts = 'H';" in text

    def test_case_adversaries_semicolon_value_and_trailing_comment(self):
        # Audit #2: a ';' inside the value string is fine (the
        # pattern anchors on the final ';'); a trailing comment
        # must not hide the case.
        src = ("<?php\n\nenum Odd: string\n{\n"
               "    case Semi = 'a;b';\n"
               "    case Plain = 'n'; // the noted one\n"
               "}\n")
        out = _outline(src, "php", "o.php")
        assert out["Odd.Semi"].name == "Semi"
        assert out["Odd.Plain"].name == "Plain"


# ---------------------------------------------------------------------------
# Item B — MCP parity tools
# ---------------------------------------------------------------------------

def _fixture_project(tmp_path):
    (tmp_path / "main.py").write_text("import util\n\nutil.go()\n")
    (tmp_path / "util.py").write_text("def go():\n    return 1\n")
    (tmp_path / "orphan.py").write_text("def unused():\n    return 2\n")
    rows = [
        {"at": "2026-10-01T00:00:00+00:00", "kind": "export",
         "before_tokens": 1000, "after_tokens": 400, "saved_tokens": 600},
        {"at": "2026-10-08T00:00:00+00:00", "kind": "export",
         "before_tokens": 1200, "after_tokens": 500, "saved_tokens": 700},
    ]
    (tmp_path / ".ghostslice-history.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    return tmp_path


class TestMcpParity:
    def test_tools_list_is_the_nine(self):
        resp = handle_message({"jsonrpc": "2.0", "id": 1,
                               "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == {"scan_project", "slice_file", "estimate_cost",
                         "export_bundle", "check_secrets", "lint_project",
                         "project_graph", "project_history", "doctor"}

    def test_project_graph_fixture(self, tmp_path):
        root = _fixture_project(tmp_path)
        payload, err = _call("project_graph", {"path": str(root)})
        assert err is None
        assert payload["entry_points"] == ["main.py"]
        assert payload["edge_count"] == 1
        assert payload["unreachable"] == ["orphan.py"]
        by_path = {f["path"]: f for f in payload["files"]}
        assert by_path["main.py"]["imports"] == ["util.py"]
        assert by_path["util.py"]["importers"] == ["main.py"]
        assert payload["files_truncated"] is False

    def test_project_graph_cap(self, tmp_path):
        for i in range(105):
            (tmp_path / f"m{i:03d}.py").write_text("x = 1\n")
        payload, err = _call("project_graph", {"path": str(tmp_path)})
        assert err is None
        assert payload["files_total"] == 105
        assert len(payload["files"]) == 100
        assert payload["files_truncated"] is True

    def test_project_graph_missing_path_is_an_error_result(self):
        payload, err = _call("project_graph",
                             {"path": "/nonexistent-gs-polish5"})
        assert payload is None and err

    def test_project_history_fixture(self, tmp_path):
        root = _fixture_project(tmp_path)
        payload, err = _call("project_history", {"path": str(root)})
        assert err is None
        assert payload["runs"] == 2
        assert payload["total_saved_tokens"] == 1300
        assert "records" not in payload  # never the raw dump
        pct = payload["aggregates"]["percentiles"]["saved_tokens"]
        assert pct == {"p50": 650.0, "p90": 690.0}

    def test_project_history_filters_compose(self, tmp_path):
        root = _fixture_project(tmp_path)
        payload, _ = _call("project_history",
                           {"path": str(root), "top": 1})
        assert payload["runs"] == 1
        assert payload["filter"]["runs_total"] == 2
        payload, _ = _call("project_history",
                           {"path": str(root), "since": "2026-10-05"})
        assert payload["runs"] == 1
        payload, err = _call("project_history",
                             {"path": str(root), "since": "bogus"})
        assert payload is None and "unrecognised" in err

    def test_project_history_empty_project_is_honest(self, tmp_path):
        payload, err = _call("project_history", {"path": str(tmp_path)})
        assert err is None
        assert payload["runs"] == 0
        assert payload["aggregates"]["mean_saved_pct"] is None

    def test_project_history_detail_cap(self, tmp_path):
        rows = [{"at": f"2026-09-{(i % 28) + 1:02d}T00:00:00+00:00",
                 "kind": "export", "before_tokens": 100,
                 "after_tokens": 40, "saved_tokens": 60}
                for i in range(60)]
        (tmp_path / ".ghostslice-history.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))
        payload, err = _call("project_history", {"path": str(tmp_path)})
        assert err is None
        assert payload["runs"] == 60
        assert len(payload["runs_detail"]) == 50
        assert payload["runs_detail_truncated"] is True
        assert payload["runs_detail_total"] == 60

    def test_doctor_tool(self, tmp_path):
        root = _fixture_project(tmp_path)
        payload, err = _call("doctor", {"path": str(root)})
        assert err is None
        assert len(payload["checks"]) == 10
        assert payload["ok"] == (payload["counts"]["fail"] == 0)
        assert sum(payload["counts"].values()) == 10


# ---------------------------------------------------------------------------
# Item C — README landing page + docs/ integrity
# ---------------------------------------------------------------------------

DOC_FILES = ["commands.md", "profiles.md", "history.md",
             "operations.md", "languages.md", "dashboard.md",
             "plugins.md", "reference.md"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _no_code_lines(text):
    in_fence = False
    for ln in text.splitlines():
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield re.sub(r"`[^`]*`", "", ln)


def _headings(text):
    in_fence = False
    out = []
    for ln in text.splitlines():
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(ln)
        if m:
            out.append(m.group(2).strip())
    return out


def _gh_anchor(heading_text):
    a = heading_text.strip().lower()
    a = re.sub(r"[^\w\s-]", "", a, flags=re.UNICODE)
    return a.replace(" ", "-")


def _anchors(text):
    seen = Counter()
    out = set()
    for h in _headings(text):
        a = _gh_anchor(h)
        if seen[a]:
            a = f"{a}-{seen[a]}"
        seen[a] += 1
        out.add(a)
    return out


class TestDocsStructure:
    def test_readme_is_a_landing_page(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        # comfortably under the L001 oversize threshold (20,000)
        assert estimate_tokens(text, "markdown") < 20000
        for heading in ("## Install", "## Quickstart", "## What's in 1.0",
                        "## Documentation", "## Troubleshooting",
                        "### Known warnings on this repo", "## Tests",
                        "## Layout"):
            assert heading in text
        assert "four warnings" in text

    def test_docs_files_exist_and_are_linked(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for name in DOC_FILES:
            assert (REPO / "docs" / name).is_file(), name
            assert f"docs/{name}" in readme, name

    def test_moved_sections_live_in_docs(self):
        commands = (REPO / "docs" / "commands.md").read_text(
            encoding="utf-8")
        for heading in ("## Symbol-level slicing (v0.18)",
                        "## Call graph + dead functions (v0.19)",
                        "## Context lint (v0.11)"):
            assert heading in commands
        plugins = (REPO / "docs" / "plugins.md").read_text(
            encoding="utf-8")
        assert plugins.startswith("# Plugins")
        profiles = (REPO / "docs" / "profiles.md").read_text(
            encoding="utf-8")
        assert "## CI pack: one gate command (v0.24)" in profiles

    def test_every_relative_link_resolves(self):
        files = {"README.md": REPO / "README.md"}
        for name in DOC_FILES:
            files[f"docs/{name}"] = REPO / "docs" / name
        texts = {k: p.read_text(encoding="utf-8")
                 for k, p in files.items()}
        anchors = {k: _anchors(t) for k, t in texts.items()}
        broken = []
        for name, text in texts.items():
            base = Path(name).parent
            for target in _LINK_RE.findall(
                    "\n".join(_no_code_lines(text))):
                if target.startswith(("http://", "https://",
                                      "mailto:")):
                    continue
                if target.startswith("#"):
                    if target[1:] not in anchors[name]:
                        broken.append(f"{name}: {target}")
                    continue
                path, _, frag = target.partition("#")
                dest = (base / path).as_posix()
                if not (REPO / dest).exists():
                    broken.append(f"{name}: missing file {target}")
                    continue
                if frag and dest in anchors \
                        and frag not in anchors[dest]:
                    broken.append(f"{name}: missing anchor {target}")
        assert not broken, broken
